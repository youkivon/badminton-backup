# -*- coding: utf-8 -*-
"""
VLM V2 解析器健壮性测试
覆盖：SKIP帧、低质量占位、异常格式、VLM超时、球坐标空值
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from vlm_analyzer_v2 import _parse_stage2_result

IMG = "/tmp/test_frame.jpg"

# ─────────────────────────────────────────
# Case 1: 纯 SKIP 响应（无标签格式）
# ─────────────────────────────────────────
def test_skip_plain():
    r = _parse_stage2_result(IMG, "SKIP")
    assert r["action_type"] == "SKIP", f"action_type={r['action_type']}"
    assert r["quality_rating"] == 0, f"rating={r['quality_rating']}"
    print("  ✅ Case1: SKIP plain → action_type=SKIP, rating=0")

# ─────────────────────────────────────────
# Case 2: 动作类型含"无法判断"关键词
# 注意：即使 VLM 同时返回评分，action_type=SKIP 在 batch 阶段会被 continue 丢弃
# 该帧不进报告，所以评分无实际影响。此测试只验证 action_type 被正确识别为 SKIP。
# ─────────────────────────────────────────
def test_skip_in_action_type():
    r = _parse_stage2_result(IMG, "动作类型: 无法判断\n综合评分: 8\n发力链: 7")
    assert r["action_type"] == "SKIP", f"action_type={r['action_type']}"
    print("  ✅ Case2: '无法判断' in action_type → action_type=SKIP（batch丢弃）")

# ─────────────────────────────────────────
# Case 3: 正常格式解析
# ─────────────────────────────────────────
def test_normal_format():
    text = (
        "动作类型: 正手杀球\n"
        "综合评分: 7\n"
        "发力链: 6\n"
        "闪腕: 7\n"
        "步伐: 6\n"
        "拍面控制: 7\n"
        "整体协调: 6\n"
        "主要问题: E3-架肘\n"
        "改进建议: 引拍时保持肘低于肩"
    )
    r = _parse_stage2_result(IMG, text)
    assert r["action_type"] == "正手杀球"
    assert r["quality_rating"] == 7
    assert r["发力链"] == 6
    assert r["闪腕"] == 7
    assert r["步伐"] == 6
    assert r["拍面控制"] == 7
    assert r["整体协调"] == 6
    assert r["errors"] == ["E3-架肘"]
    assert r["suggestions"] == ["引拍时保持肘低于肩"]
    print("  ✅ Case3: 正常格式 → 各字段正确解析")

# ─────────────────────────────────────────
# Case 4: VLM 未返回任何评分（解析失败）
# ─────────────────────────────────────────
def test_missing_ratings():
    r = _parse_stage2_result(IMG, "动作类型: 正手抽球\n发力链: 6")
    assert r["quality_rating"] == 0, f"rating={r['quality_rating']}（应强制置0）"
    assert r["闪腕"] == 0, f"闪腕={r['闪腕']}"
    assert r["步伐"] == 0, f"步伐={r['步伐']}"
    print("  ✅ Case4: 缺少评分字段 → rating=0, 其余维度=0")

# ─────────────────────────────────────────
# Case 5: ball_info=None 调用（空值保护）
# ─────────────────────────────────────────
def test_ball_info_none():
    r = _parse_stage2_result(IMG, "动作类型: 杀球\n综合评分: 6", ball_info=None)
    assert not r["ball_detected"]
    assert r["ball_cx"] is None
    assert r["ball_cy"] is None
    print("  ✅ Case5: ball_info=None → 空值保护不抛异常")

# ─────────────────────────────────────────
# Case 6: ball_info 缺少字段
# ─────────────────────────────────────────
def test_ball_info_partial():
    r = _parse_stage2_result(IMG, "动作类型: 杀球\n综合评分: 6", ball_info={"found": True})
    assert r["ball_detected"]
    assert r["ball_cx"] is None  # 缺失字段
    assert r["ball_cy"] is None
    print("  ✅ Case6: ball_info 缺字段 → 用 {} .get() 不抛异常")

# ─────────────────────────────────────────
# Case 7: 评分超出 0-10 范围
# ─────────────────────────────────────────
def test_rating_clamp():
    text = "动作类型: 杀球\n综合评分: 15\n发力链: -3\n闪腕: 12"
    r = _parse_stage2_result(IMG, text)
    assert r["quality_rating"] == 10, f"rating={r['quality_rating']}（应clamp到10）"
    assert r["发力链"] == 0, f"发力链={r['发力链']}（应clamp到0）"
    assert r["闪腕"] == 10, f"闪腕={r['闪腕']}（应clamp到10）"
    print("  ✅ Case7: 评分超出范围 → clamp到[0,10]")

# ─────────────────────────────────────────
# Case 8: 评分含小数点
# ─────────────────────────────────────────
def test_rating_decimal():
    text = "动作类型: 杀球\n综合评分: 7.5\n发力链: 6.8"
    r = _parse_stage2_result(IMG, text)
    assert r["quality_rating"] == 7, "取整数部分"
    assert r["发力链"] == 6
    print("  ✅ Case8: 评分含小数 → 取整数部分")

# ─────────────────────────────────────────
# Case 9: 字段名含多余空格
# ─────────────────────────────────────────
def test_spaced_labels():
    text = "动作类型:  正手杀球\n  综合评分:  8"
    r = _parse_stage2_result(IMG, text)
    assert r["action_type"] == "正手杀球"
    print("  ✅ Case9: 字段名前多余空格 → strip后匹配")

# ─────────────────────────────────────────
# Case 10: 标签格式错误（无冒号）
# ─────────────────────────────────────────
def test_no_colon():
    text = "动作类型 正手杀球\n综合评分为8\n发力链=6"
    r = _parse_stage2_result(IMG, text)
    assert r["action_type"] == "无法判断"  # 未匹配到标签
    assert r["quality_rating"] == 0
    print("  ✅ Case10: 无冒号格式 → 无法解析，返回无法判断+rating=0")

# ─────────────────────────────────────────
# Case 11: 全部维度评分缺失
# ─────────────────────────────────────────
def test_all_ratings_missing():
    text = "动作类型: 正手抽球\n主要问题: 无\n改进建议: 保持手腕放松"
    r = _parse_stage2_result(IMG, text)
    assert r["quality_rating"] == 0
    assert r["发力链"] == 0
    assert r["闪腕"] == 0
    assert r["步伐"] == 0
    print("  ✅ Case11: 所有评分缺失 → 全部强制置0")


if __name__ == "__main__":
    print("\n=== V2 解析器健壮性测试 ===")
    cases = [
        (test_skip_plain,         "Case1 纯SKIP"),
        (test_skip_in_action_type,"Case2 无法判断关键词"),
        (test_normal_format,      "Case3 正常格式"),
        (test_missing_ratings,    "Case4 评分缺失"),
        (test_ball_info_none,     "Case5 ball_info=None"),
        (test_ball_info_partial,  "Case6 ball_info部分字段"),
        (test_rating_clamp,       "Case7 评分clamp"),
        (test_rating_decimal,     "Case8 评分小数"),
        (test_spaced_labels,      "Case9 字段名空格"),
        (test_no_colon,           "Case10 无冒号格式"),
        (test_all_ratings_missing,"Case11 全部评分缺失"),
    ]
    for fn, name in cases:
        try:
            fn()
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
        except Exception as e:
            print(f"  💥 {name}: {type(e).__name__}: {e}")

    print("\n=== 全部完成 ===\n")
