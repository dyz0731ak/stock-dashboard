"""The requested cash indices and spot instruments, shared with SSG."""
MARKET_INDICES = [
    dict(id='nk225', ticker='^N225', label='日経225', decimals=2, unit='円', instrument_type='INDEX'),
    dict(id='dow', ticker='^DJI', label='NYダウ', decimals=2, unit='pt', instrument_type='INDEX'),
    dict(id='nasdaq', ticker='^IXIC', label='NASDAQ総合指数', decimals=2, unit='pt', instrument_type='INDEX'),
    dict(id='usdjpy', ticker='JPY=X', label='USD/JPY', decimals=3, unit='円 / 米ドル', instrument_type='CURRENCY'),
    dict(id='sox', ticker='^SOX', label='SOX指数', decimals=2, unit='pt', instrument_type='INDEX'),
    dict(id='gold', ticker='XAU', label='金スポット', decimals=2, unit='USD / トロイオンス', instrument_type='SPOT'),
]
TSE_INDICES = [
    dict(id='tse-prime', ticker='TsePrimeMarketIndex', label='東証プライム市場指数', decimals=2, unit='pt', instrument_type='INDEX'),
    dict(id='tse-standard', ticker='TseStandardMarketIndex', label='東証スタンダード市場指数', decimals=2, unit='pt', instrument_type='INDEX'),
    dict(id='tse-growth', ticker='TseGrowthMarketIndex', label='東証グロース市場指数', decimals=2, unit='pt', instrument_type='INDEX'),
]
