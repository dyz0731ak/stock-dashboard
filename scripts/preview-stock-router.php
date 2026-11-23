<?php
// Router for the local PHP server. Apache rewrites this path in production.
if (strpos($_SERVER['REQUEST_URI'], '/data/stock_history/') === 0) {
    require __DIR__ . '/../chart/stock-history.php';
    return true;
}
return false;
