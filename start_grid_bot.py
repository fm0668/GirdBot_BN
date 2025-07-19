#!/usr/bin/env python3
"""
网格交易机器人启动脚本
包含启动清理和优雅停止功能
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import main

def setup_logging():
    """设置日志配置"""
    # 创建日志目录
    os.makedirs("log", exist_ok=True)
    
    # 生成带时间戳的日志文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"log/grid_bot_{timestamp}.log"
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"日志文件: {log_filename}")
    return logger

def print_banner():
    """打印启动横幅"""
    banner = """
    ╔══════════════════════════════════════════════════════════════╗
    ║                    网格交易机器人 v2.1.0                      ║
    ║                                                              ║
    ║  新功能:                                                     ║
    ║  ✅ 启动时自动清理账户 (撤单+平仓)                            ║
    ║  ✅ 优雅停止机制 (Ctrl+C 安全退出)                           ║
    ║  ✅ 完善的异常处理和日志记录                                  ║
    ║                                                              ║
    ║  使用说明:                                                   ║
    ║  • 按 Ctrl+C 可以安全停止程序                                ║
    ║  • 程序会自动清理所有挂单和持仓后退出                         ║
    ║  • 启动前会自动清理账户确保干净状态                           ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)

def check_config():
    """检查配置文件"""
    try:
        from config import API_KEY, API_SECRET, COIN_NAME, CONTRACT_TYPE
        
        if not API_KEY or not API_SECRET:
            print("❌ 错误: 请在 config.py 中配置 API_KEY 和 API_SECRET")
            return False
            
        if not COIN_NAME or not CONTRACT_TYPE:
            print("❌ 错误: 请在 config.py 中配置 COIN_NAME 和 CONTRACT_TYPE")
            return False
            
        print(f"✅ 配置检查通过")
        print(f"   交易对: {COIN_NAME}/{CONTRACT_TYPE}")
        return True
        
    except ImportError as e:
        print(f"❌ 错误: 无法导入配置文件: {e}")
        print("   请确保 config.py 文件存在且配置正确")
        return False

async def run_bot():
    """运行机器人"""
    logger = setup_logging()
    
    try:
        print_banner()
        
        # 检查配置
        if not check_config():
            return
        
        print("\n" + "="*60)
        print("🚀 启动网格交易机器人...")
        print("="*60)
        
        # 运行主程序
        await main()
        
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
        print("\n✅ 程序已安全停止")
    except Exception as e:
        logger.error(f"程序运行异常: {e}", exc_info=True)
        print(f"\n❌ 程序运行异常: {e}")
        print("请检查日志文件获取详细信息")
    finally:
        print("\n" + "="*60)
        print("程序已退出")
        print("="*60)

def main_entry():
    """主入口函数"""
    try:
        # 检查Python版本
        if sys.version_info < (3, 8):
            print("❌ 错误: 需要 Python 3.8 或更高版本")
            sys.exit(1)
        
        # 运行异步主函数
        asyncio.run(run_bot())
        
    except KeyboardInterrupt:
        print("\n程序被中断")
    except Exception as e:
        print(f"\n启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main_entry()
