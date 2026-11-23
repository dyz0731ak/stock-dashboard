<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-cache, must-revalidate');

function chartError(int $status): void
{
    http_response_code($status);
    echo '{"error":"Stock history unavailable"}';
    exit;
}

function tokyoTime(int $timestamp): DateTimeImmutable
{
    return (new DateTimeImmutable('@' . $timestamp))->setTimezone(new DateTimeZone('Asia/Tokyo'));
}

function fetchBars(string $code, string $interval, bool $summary): array
{
    [$resolution, $range] = [
        '5m' => ['5m', '1mo'],
        '1h' => ['60m', '2y'],
        '1d' => ['1d', $summary ? '5d' : '10y'],
    ][$interval];
    $query = http_build_query(['interval' => $resolution, 'range' => $range, 'includePrePost' => 'false']);
    $url = "https://query1.finance.yahoo.com/v8/finance/chart/{$code}.T?{$query}";
    $request = curl_init($url);
    curl_setopt_array($request, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 3,
        CURLOPT_TIMEOUT => 8,
        CURLOPT_USERAGENT => 'Mozilla/5.0',
        CURLOPT_ENCODING => '',
        CURLOPT_HTTPHEADER => ['Accept: application/json'],
    ]);
    $body = curl_exec($request);
    $status = curl_getinfo($request, CURLINFO_RESPONSE_CODE);
    curl_close($request);
    if ($status === 404) {
        return [];
    }
    if ($status !== 200 || !is_string($body)) {
        throw new RuntimeException('Upstream request failed');
    }
    $result = json_decode($body, true, 64, JSON_THROW_ON_ERROR)['chart']['result'][0] ?? [];
    $granularity = $result['meta']['dataGranularity'] ?? null;
    $symbol = $result['meta']['symbol'] ?? null;
    $quote = $result['indicators']['quote'][0] ?? null;
    if ($symbol !== $code . '.T' || !is_array($quote)
        || ($granularity !== $resolution && !($interval === '1h' && $granularity === '1h'))) {
        throw new RuntimeException('Unexpected upstream response');
    }

    $bars = [];
    foreach ($result['timestamp'] ?? [] as $index => $timestamp) {
        $open = $quote['open'][$index] ?? null;
        $high = $quote['high'][$index] ?? null;
        $low = $quote['low'][$index] ?? null;
        $close = $quote['close'][$index] ?? null;
        if (!is_int($timestamp) || !is_numeric($open) || !is_numeric($high)
            || !is_numeric($low) || !is_numeric($close)
            || $low <= 0 || $low > min($open, $close) || $high < max($open, $close)) {
            continue;
        }
        $volume = $quote['volume'][$index] ?? null;
        $bar = ['time' => $timestamp, 'open' => $open, 'high' => $high,
            'low' => $low, 'close' => $close, 'volume' => $volume];
        if ($interval !== '1d' && $timestamp === ($result['meta']['regularMarketTime'] ?? null)) {
            $time = tokyoTime($timestamp);
            if ($time->format('H:i:s') === '15:30:00') {
                // The closing auction can arrive as a separate quote without volume.
                $barStart = $timestamp - ($interval === '1h' ? 1800 : 300);
                $previous = $bars[$barStart] ?? $bar;
                $previous['time'] = $barStart;
                $previous['high'] = max($previous['high'], $high);
                $previous['low'] = min($previous['low'], $low);
                $previous['close'] = $close;
                $previous['volume'] = isset($bars[$barStart])
                    ? ($previous['volume'] !== null && $volume ? $previous['volume'] + $volume : null)
                    : ($volume ?: null);
                $bars[$barStart] = $previous;
                continue;
            }
            $minutes = $interval === '5m' ? 5 : 60;
            if ($time->format('s') !== '00' || (int) $time->format('i') % $minutes !== 0 || !$volume) {
                continue;
            }
        }
        $bars[$timestamp] = $bar;
    }
    ksort($bars, SORT_NUMERIC);
    return array_values($bars);
}

function calendarBars(array $bars, string $interval): array
{
    $groups = [];
    foreach ($bars as $bar) {
        $day = tokyoTime($bar['time']);
        $period = $interval === '1w'
            ? $day->modify('monday this week')
            : $day->modify('first day of this month');
        $time = $period->setTime(9, 0)->getTimestamp();
        if (!isset($groups[$time])) {
            $bar['time'] = $time;
            $groups[$time] = $bar;
            continue;
        }
        $group = &$groups[$time];
        $group['high'] = max($group['high'], $bar['high']);
        $group['low'] = min($group['low'], $bar['low']);
        $group['close'] = $bar['close'];
        if ($bar['volume'] !== null) {
            $group['volume'] = ($group['volume'] ?? 0) + $bar['volume'];
        }
        unset($group);
    }
    return array_values($groups);
}

function cachedBars(string $code, string $interval, bool $summary): array
{
    $master = json_decode((string) file_get_contents(__DIR__ . '/../data/jpx_master.json'), true);
    if (!in_array($code, array_column($master['stocks'] ?? [], 'code'), true)) {
        chartError(404);
    }

    $directory = sys_get_temp_dir() . '/toride-stock-chart-' . substr(hash('sha256', __DIR__), 0, 16);
    if (!is_dir($directory) && !@mkdir($directory, 0700) && !is_dir($directory)) {
        throw new RuntimeException('Cache directory unavailable');
    }
    $path = $directory . '/' . $code . '-' . ($summary ? 'summary' : $interval) . '.json';
    $ttl = $summary ? 300 : 60;
    $read = static function () use ($path): ?array {
        clearstatcache(true, $path);
        return is_file($path) ? json_decode((string) @file_get_contents($path), true) : null;
    };
    $entry = $read();
    if ($entry !== null && time() < $entry['next']) {
        return $entry;
    }
    // Concurrent viewers share one upstream fetch per symbol and interval.
    $lock = @fopen($path . '.lock', 'c');
    if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
        if (is_resource($lock)) {
            fclose($lock);
        }
        if ($entry !== null) {
            $entry['stale'] = true;
            return $entry;
        }
        throw new RuntimeException('Refresh in progress');
    }
    try {
        $entry = $read();
        if ($entry !== null && time() < $entry['next']) {
            return $entry;
        }
        try {
            $bars = fetchBars($code, $interval, $summary);
            if (!$bars && !empty($entry['bars'])) {
                throw new RuntimeException('Upstream data missing');
            }
            $entry = ['bars' => $bars, 'next' => time() + $ttl, 'stale' => false];
        } catch (Throwable $error) {
            if ($entry === null) {
                throw $error;
            }
            $entry['next'] = time() + $ttl;
            $entry['stale'] = true;
        }
        $temp = $path . '.tmp';
        if (@file_put_contents($temp, json_encode($entry, JSON_THROW_ON_ERROR)) !== false) {
            @rename($temp, $path);
        }
        return $entry;
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

$method = $_SERVER['REQUEST_METHOD'] ?? '';
if ($method !== 'GET' && $method !== 'HEAD') {
    header('Allow: GET, HEAD');
    chartError(405);
}
$requestPath = parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH);
if (!is_string($requestPath)
    || !preg_match('~^/data/stock_history/([0-9][A-Z0-9]{3})/(5m|1h|1d|1w|1mo)\.json$~D', $requestPath, $match)) {
    chartError(404);
}
[, $code, $interval] = $match;
$summary = $interval === '1d' && ($_GET['summary'] ?? '') === '1';
try {
    $sourceInterval = in_array($interval, ['1w', '1mo'], true) ? '1d' : $interval;
    $entry = cachedBars($code, $sourceInterval, $summary);
    $bars = $entry['bars'];
    if ($summary) {
        $bars = array_slice($bars, -2);
    } elseif ($interval !== $sourceInterval) {
        $bars = calendarBars($bars, $interval);
    }
    $body = json_encode(['code' => $code, 'interval' => $interval,
        'source' => 'Yahoo Finance（東証20分遅延）', 'stale' => $entry['stale'], 'bars' => $bars],
        JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE);
    $etag = '"' . hash('sha256', $body) . '"';
    header('ETag: ' . $etag);
    if (($_SERVER['HTTP_IF_NONE_MATCH'] ?? '') === $etag) {
        http_response_code(304);
        exit;
    }
    if ($method === 'GET') {
        echo $body;
    }
} catch (Throwable $error) {
    error_log('Stock chart upstream: ' . $error->getMessage());
    header('Retry-After: 60');
    chartError(503);
}
