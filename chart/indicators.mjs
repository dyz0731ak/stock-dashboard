// Wilder's RMA starts with the mean of the first 14 close-to-close changes.
export function withRsi(bars, length = 14) {
  let gain = 0;
  let loss = 0;
  const recent = [];
  let sum = 0;
  return bars.map((bar, index) => {
    if (index === 0) return bar;
    const change = bar.close - bars[index - 1].close;
    const up = Math.max(change, 0);
    const down = Math.max(-change, 0);
    if (index <= length) {
      gain += up / length;
      loss += down / length;
    } else {
      gain = (gain * (length - 1) + up) / length;
      loss = (loss * (length - 1) + down) / length;
    }
    if (index < length) return bar;
    const rsi = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
    recent.push(rsi);
    sum += rsi;
    if (recent.length > length) sum -= recent.shift();
    return { ...bar, rsi, sma: recent.length === length ? sum / length : undefined };
  });
}
