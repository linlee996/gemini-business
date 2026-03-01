"""
模型配置系统

功能：
- 模型名称解析（前缀处理）
- 模型列表生成
- 特性检测（抗截断）

命名规范：
- 基础模型：gemini-2.5-pro
- 抗截断：流式抗截断/gemini-2.5-pro

注意：Business API (biz-discoveryengine) 不支持 thinkingConfig，
因此 nothinking/maxthinking 功能不可用，已移除相关模型变体
"""

from typing import List, Optional, Tuple


# ==================== 基础模型列表 ====================

BASE_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-3-pro-preview",
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
]

# 功能前缀（只保留抗截断）
FEATURE_PREFIXES = ["流式抗截断/"]


# ==================== 模型名称解析 ====================

def get_base_model_name(model_name: str) -> str:
    """
    移除模型名称中的前缀，返回基础模型名

    示例：
    - 流式抗截断/gemini-2.5-pro -> gemini-2.5-pro
    - gemini-2.5-pro -> gemini-2.5-pro
    """
    result = model_name

    # 移除前缀
    for prefix in FEATURE_PREFIXES:
        if result.startswith(prefix):
            result = result[len(prefix):]
            break

    return result


def parse_model_features(model_name: str) -> dict:
    """
    解析模型名称，提取特性

    返回：
    {
        "base_model": str,           # 基础模型名
        "is_anti_truncation": bool,  # 是否抗截断
    }
    """
    features = {
        "base_model": "",
        "is_anti_truncation": False,
    }

    working_name = model_name

    # 检测抗截断前缀
    if working_name.startswith("流式抗截断/"):
        features["is_anti_truncation"] = True
        working_name = working_name[len("流式抗截断/"):]

    # 获取基础模型名
    features["base_model"] = working_name

    return features


# ==================== 特性检测函数 ====================

def is_anti_truncation_model(model_name: str) -> bool:
    """检查是否为抗截断模型"""
    return model_name.startswith("流式抗截断/")


# ==================== 以下函数保留但不再使用（Business API 不支持） ====================

def get_thinking_settings(model_name: str) -> Tuple[Optional[int], bool]:
    """
    获取思考配置（Business API 不支持，始终返回 None）

    保留此函数以保持接口兼容性
    """
    return None, True


def is_fake_streaming_model(model_name: str) -> bool:
    """检查是否为假流式模型（已移除该功能）"""
    return False


def is_search_model(model_name: str) -> bool:
    """检查是否为搜索模型（已移除该功能）"""
    return False


# ==================== 模型列表生成 ====================

def get_available_models() -> List[str]:
    """
    生成模型列表（只包含基础模型和抗截断变体）
    """
    models = []

    for base_model in BASE_MODELS:
        # 基础模型
        models.append(base_model)
        # 流式抗截断模型
        models.append(f"流式抗截断/{base_model}")

    return models


def get_model_mapping() -> dict:
    """
    生成模型映射字典
    """
    mapping = {"gemini-auto": None}

    for model in get_available_models():
        base_model = get_base_model_name(model)
        mapping[model] = base_model

    return mapping


# ==================== 测试 ====================

if __name__ == "__main__":
    print("生成的模型列表:")
    for m in get_available_models():
        print(f"  {m}")

    print()
    print("模型解析测试:")
    test_models = [
        "gemini-2.5-pro",
        "流式抗截断/gemini-2.5-pro",
        "gemini-2.5-flash",
        "流式抗截断/gemini-3-pro-preview",
    ]
    for model in test_models:
        features = parse_model_features(model)
        print(f"  {model}")
        print(f"    基础模型: {features['base_model']}")
        print(f"    抗截断: {features['is_anti_truncation']}")
