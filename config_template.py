# ==================== 配置文件 ====================
# 注意：请将此文件添加到 .gitignore 中，避免API密钥泄露

# ==================== API 配置 ====================
API_KEY = ""  # 替换为你的 API Key
API_SECRET = ""  # 替换为你的 API Secret

# ==================== 交易配置 ====================
COIN_NAME = "DOGE"  # 交易币种
CONTRACT_TYPE = "USDC"  # 合约类型：USDT 或 USDC
GRID_SPACING = 0.001  # 网格间距 (0.1%)
INITIAL_QUANTITY = 50  # 初始交易数量 (币数量) - 确保订单价值大于5 USDC (DOGE约0.12，50*0.12=6 USDC)
LEVERAGE = 20  # 杠杆倍数

# ==================== 动态数量配置 ====================
ENABLE_DYNAMIC_QUANTITY = True   # 是否启用动态数量计算
ACCOUNT_USAGE_RATIO = 0.6        # 账户资金使用比例 (60%)
SINGLE_ORDER_RATIO = 0.1         # 单笔订单占可用资金比例 (10%)
MIN_ORDER_VALUE = 5.0            # 最小订单价值 (USDC)
MAX_ORDER_VALUE = 100.0          # 最大订单价值 (USDC)
QUANTITY_CACHE_DURATION = 30     # 数量计算缓存时间 (秒)

# ==================== 杠杆优化配置 ====================
LEVERAGE_BASED_CALCULATION = True   # 启用基于杠杆的资金计算
LEVERAGE_ORDER_RATIO = 0.04         # 单笔订单占杠杆后资金的比例 (4%)
USE_TOTAL_EQUITY = True              # 使用总权益而非可用余额作为基准

# ==================== WebSocket 配置 ====================
WEBSOCKET_URL = "wss://fstream.binance.com/ws"  # WebSocket URL

# ==================== 风控配置 ====================
# 注意：已删除装死模式相关配置
# POSITION_THRESHOLD - 已删除，不再使用装死模式
# POSITION_LIMIT, MAX_POSITION_RATIO, STOP_LOSS_RATIO, VOLATILITY_WINDOW - 未使用，已删除
# MIN_GRID_SPACING, MAX_GRID_SPACING - 未使用，已删除

# ==================== 时间配置 ====================
SYNC_TIME = 10  # 同步时间（秒）
ORDER_FIRST_TIME = 10  # 首单间隔时间

# ==================== 对冲配置 ====================
ENABLE_HEDGE_INITIALIZATION = True  # 启用对冲初始化模式
HEDGE_INIT_DELAY = 1                 # 对冲初始化延迟（秒）- 确保双向同时开仓

# ==================== API频率控制配置 ====================
# 基于币安期货API限制计算的冷却时间
# fetch_open_orders权重: 单个交易对=1, 所有交易对=40
# 保守估计API限制: 1200 weight/分钟 = 20 weight/秒

ORDERS_SYNC_COOLDOWN = 3      # 标准订单同步冷却时间（秒）- 保守设置
FAST_SYNC_COOLDOWN = 1        # 快速市场订单同步冷却时间（秒）- 1秒=1weight，安全
PRICE_CHANGE_THRESHOLD = 0.002 # 价格变化阈值，超过此值认为是快速波动（0.2%）
FAST_MARKET_WINDOW = 10       # 快速市场检测窗口时间（秒）

# API限制相关配置
API_WEIGHT_LIMIT_PER_MINUTE = 1200  # 每分钟权重限制（保守估计）
FETCH_ORDERS_WEIGHT = 1              # fetch_open_orders单个交易对权重
SAFETY_MARGIN = 0.8                  # 安全边际，只使用80%的限制
