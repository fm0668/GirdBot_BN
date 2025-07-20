import asyncio
import logging
import os
import signal
import sys
from config import (
    API_KEY, API_SECRET, COIN_NAME, CONTRACT_TYPE,
    GRID_SPACING, INITIAL_QUANTITY, LEVERAGE
)
from exchange_client import ExchangeClient
from websocket_handler import WebSocketHandler
from grid_strategy import GridStrategy

# ==================== 日志配置 ====================
script_name = os.path.splitext(os.path.basename(__file__))[0]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"log/{script_name}.log"),  # 日志文件
        logging.StreamHandler(),  # 控制台输出
    ],
)
logger = logging.getLogger()


class GridTradingBot:
    """网格交易机器人主类"""

    def __init__(self, api_key, api_secret, coin_name, contract_type, grid_spacing, initial_quantity, leverage):
        # 初始化各个组件
        self.exchange_client = ExchangeClient(api_key, api_secret, coin_name, contract_type)
        self.grid_strategy = GridStrategy(self.exchange_client)
        self.websocket_handler = WebSocketHandler(self.exchange_client, self.grid_strategy)

        # 停止信号标志
        self.stop_signal = False
        self.cleanup_completed = False

        # 检查持仓模式，如果不是双向持仓模式则停止程序
        self.exchange_client.check_and_enable_hedge_mode()

        logger.info(f"网格交易机器人初始化完成")
        logger.info(f"交易对: {coin_name}/{contract_type}")
        logger.info(f"网格间距: {grid_spacing}")
        logger.info(f"初始数量: {initial_quantity}")
        logger.info(f"杠杆倍数: {leverage}")

    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            logger.info(f"收到停止信号 {signum}，开始优雅停止...")
            self.stop_signal = True
            # 通知WebSocket处理器停止
            self.websocket_handler.set_stop_signal()

        # 注册信号处理器
        signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # 终止信号
        if hasattr(signal, 'SIGBREAK'):  # Windows
            signal.signal(signal.SIGBREAK, signal_handler)

    async def startup_cleanup(self):
        """启动时清理账户"""
        logger.info("=" * 60)
        logger.info("策略启动前清理账户...")
        logger.info("=" * 60)

        try:
            # 执行账户清理
            cleanup_success = self.exchange_client.cleanup_account()

            if cleanup_success:
                logger.info("✅ 启动前账户清理成功")
            else:
                logger.warning("⚠️ 启动前账户清理不完整，但继续运行")

            # 等待一段时间确保清理完成
            await asyncio.sleep(3)

        except Exception as e:
            logger.error(f"❌ 启动前账户清理失败: {e}")
            raise

    async def graceful_shutdown(self):
        """优雅停止"""
        if self.cleanup_completed:
            return

        logger.info("=" * 60)
        logger.info("开始优雅停止策略...")
        logger.info("=" * 60)

        try:
            # 执行账户清理
            cleanup_success = self.exchange_client.cleanup_account()

            if cleanup_success:
                logger.info("✅ 优雅停止完成：所有订单已处理")
            else:
                logger.warning("⚠️ 优雅停止不完整：部分订单可能未处理")

            self.cleanup_completed = True

        except Exception as e:
            logger.error(f"❌ 优雅停止过程中发生错误: {e}")
            self.cleanup_completed = True

    async def run(self):
        """启动机器人"""
        # 设置信号处理器
        self.setup_signal_handlers()

        # 启动前清理账户
        await self.startup_cleanup()

        # 初始化时获取一次持仓数据
        long_position, short_position = self.exchange_client.get_position()
        self.grid_strategy.update_positions(long_position, short_position)
        logger.info(f"初始化持仓: 多头 {long_position} 张, 空头 {short_position} 张")

        # 等待状态同步完成
        await asyncio.sleep(5)

        # 初始化时获取一次挂单状态
        self.grid_strategy.check_orders_status()
        orders_info = self.grid_strategy.get_orders_info()
        logger.info(f"初始化挂单状态: {orders_info}")

        logger.info("=" * 60)
        logger.info("🚀 网格交易策略正式启动")
        logger.info("=" * 60)

        try:
            # 启动WebSocket处理器
            websocket_task = asyncio.create_task(self.websocket_handler.start())

            # 启动事件驱动主循环
            strategy_loop_task = asyncio.create_task(self.grid_strategy.main_strategy_loop())

            # 监控停止信号和风险指标
            risk_log_counter = 0
            while not self.stop_signal:
                await asyncio.sleep(1)

                # 每60秒记录一次风险指标
                risk_log_counter += 1
                if risk_log_counter >= 60:
                    self.grid_strategy.log_risk_metrics()
                    risk_log_counter = 0

            # 收到停止信号，优雅关闭
            logger.info("收到停止信号，正在优雅关闭...")

            # 停止策略主循环
            await self.grid_strategy.shutdown()
            strategy_loop_task.cancel()

            # 停止WebSocket
            websocket_task.cancel()

            try:
                await asyncio.gather(websocket_task, strategy_loop_task, return_exceptions=True)
            except asyncio.CancelledError:
                logger.info("所有任务已取消")

        except Exception as e:
            if not self.stop_signal:
                logger.error(f"WebSocket处理器异常: {e}")
                raise
        finally:
            # 确保优雅停止
            await self.graceful_shutdown()


async def main():
    """主程序入口"""
    # 检查API密钥是否配置
    if not API_KEY or not API_SECRET:
        logger.error("请在 config.py 中配置 API_KEY 和 API_SECRET")
        return

    # 创建日志目录
    os.makedirs("log", exist_ok=True)

    bot = None
    try:
        # 创建并启动机器人
        bot = GridTradingBot(
            API_KEY, API_SECRET, COIN_NAME, CONTRACT_TYPE,
            GRID_SPACING, INITIAL_QUANTITY, LEVERAGE
        )

        await bot.run()

    except KeyboardInterrupt:
        logger.info("程序被用户中断 (Ctrl+C)")
        if bot:
            bot.stop_signal = True
            bot.websocket_handler.set_stop_signal()
    except Exception as e:
        logger.error(f"程序运行出错: {e}")
        if bot:
            bot.stop_signal = True
            bot.websocket_handler.set_stop_signal()
        raise
    finally:
        if bot and not bot.cleanup_completed:
            logger.info("执行最终清理...")
            await bot.graceful_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
