"""Trend Chart Generator - 生成热点实体趋势折线图"""

import matplotlib
matplotlib.use('Agg')  # 使用无界面后端

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import Dict
import os


def generate_trend_chart(
    daily_data: Dict[str, Dict[str, int]],
    output_path: str = "data/trend_chart.png",
    title: str = "热点实体趋势 (近7天)",
    figsize: tuple = (10, 5)
) -> str:
    """
    生成热点实体趋势折线图
    
    Args:
        daily_data: {entity_name: {"01-12": 10, "01-13": 15, ...}}
        output_path: 输出文件路径
        title: 图表标题
        figsize: 图表尺寸
        
    Returns:
        生成的图片路径
    """
    if not daily_data:
        return ""
    
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建图表
    fig, ax = plt.subplots(figsize=figsize)
    
    # 颜色列表
    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']
    
    # 获取日期列表（从第一个实体）
    first_entity = list(daily_data.keys())[0]
    dates = list(daily_data[first_entity].keys())
    
    # 绘制每个实体的折线
    for idx, (entity_name, counts) in enumerate(daily_data.items()):
        values = [counts.get(d, 0) for d in dates]
        color = colors[idx % len(colors)]
        
        # 截断过长的实体名
        display_name = entity_name[:15] + "..." if len(entity_name) > 15 else entity_name
        
        ax.plot(dates, values, marker='o', markersize=4, linewidth=2, 
                color=color, label=display_name)
    
    # 设置标题和标签
    ax.set_title(title, fontsize=14, fontweight='bold', pad=10)
    ax.set_xlabel('日期', fontsize=10)
    ax.set_ylabel('提及次数', fontsize=10)
    
    # 设置网格
    ax.grid(True, linestyle='--', alpha=0.3)
    
    # 设置图例
    ax.legend(loc='upper left', fontsize=8, ncol=2, framealpha=0.9)
    
    # 设置 x 轴标签旋转
    plt.xticks(rotation=45, ha='right')
    
    # 紧凑布局
    plt.tight_layout()
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    
    # 保存图片
    plt.savefig(output_path, dpi=120, bbox_inches='tight', 
                facecolor='white', edgecolor='none')
    plt.close()
    
    return output_path


if __name__ == "__main__":
    # 测试数据
    test_data = {
        "OpenAI": {"01-12": 45, "01-13": 52, "01-14": 38, "01-15": 61, "01-16": 78, "01-17": 95, "01-18": 110},
        "Hugging Face": {"01-12": 30, "01-13": 28, "01-14": 35, "01-15": 42, "01-16": 38, "01-17": 45, "01-18": 50},
        "Google DeepMind": {"01-12": 20, "01-13": 25, "01-14": 22, "01-15": 28, "01-16": 30, "01-17": 35, "01-18": 40},
    }
    
    path = generate_trend_chart(test_data, "data/test_trend.png")
    print(f"✅ 测试图表已生成: {path}")
