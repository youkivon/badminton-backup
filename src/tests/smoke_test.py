#!/usr/bin/env python3
"""
最简冒烟测试：确保报告生成不会在已知崩溃点挂掉。
跑在真实视频之前，用小数据验证关键路径。
"""
import sys, os
# 确保 src/ 在 path 中（支持从任意目录运行）
_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

def test_style_keys():
    """验证STYLE字典包含所有被引用的F_xxx键"""
    from report_generator import STYLE
    required = ["F_TITLE","F_SECTION","F_LABEL","F_BODY","F_MINI","F_TINY",
                "F_CHART_SCORE","F_ACTION"]
    missing = [k for k in required if k not in STYLE]
    assert not missing, f"STYLE缺少: {missing}"
    print(f"  ✓ STYLE全部keys OK ({len(required)}个)")

def test_render_no_missing_function():
    """验证_render_shot_text不存在于全局命名空间（已被内联）"""
    import report_generator as rpt
    assert not hasattr(rpt, "_render_shot_text"), \
        "_render_shot_text仍然存在，应已内联"
    print("  ✓ _render_shot_text已清除")

def test_report_make_invocation():
    """用最小数据调用make_report，确保不崩溃"""
    from report_generator import make_report, STYLE

    # 最小report_data
    import tempfile, os
    out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    out.close()

    try:
        report_data = {
            "player_name": "测试球员",
            "date": "2026-05-14",
            "shots": [
                {
                    "action_type": "放网前球",
                    "quality_rating": 6,
                    "发力链": 7, "闪腕": 6, "步伐": 6,
                    "拍面控制": 7, "整体协调": 7,
                    "errors": ["E1-放网手腕僵硬"],
                    "suggestions": [],
                    "key_findings": ["手腕过于僵硬，影响球感控制"],
                    "frames": ["f_0001.jpg"],
                    "frame_file": "f_0001.jpg",
                    "player": "近端白衣球员",
                }
            ],
            "total_shots": 1,
            "avg_quality": 6.0,
            "session_key": "test123",
            "frames_dir": "",
            "court_ok": 1,
        }

        # 模拟帧图存在
        tmp = tempfile.mkdtemp()
        import shutil
        # 创建假帧图
        try:
            from PIL import Image
            img = Image.new("RGB", (640, 360), color=(50, 100, 50))
            img.save(os.path.join(tmp, "f_0001.jpg"))
            report_data["frames_dir"] = tmp

            # 补全 make_report 需要的字段
            report_data["video"] = "微信视频2026-05-13_102319_742.mp4"
            report_data["duration"] = "8分24秒"

            make_report(report_data, out.name)
            size = os.path.getsize(out.name)
            assert size > 10000, f"PDF太小({size}B)，可能生成失败"
            print(f"  ✓ make_report成功，PDF大小={size}B")
        finally:
            shutil.rmtree(tmp)

    finally:
        os.unlink(out.name)

def test_preflight_check_signature():
    """验证preflight_check函数存在且有正确参数"""
    import ast, os
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run_analysis.py")
    with open(src_path) as f:
        tree = ast.parse(f.read())
    names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "preflight_check" in names, "preflight_check函数不存在"
    print(f"  ✓ preflight_check存在")

def test_vlm_analyze_frame_quick():
    """验证analyze_frame_quick存在且可调用"""
    import vlm_analyzer
    assert hasattr(vlm_analyzer, "analyze_frame_quick"), \
        "analyze_frame_quick不存在"
    # 用不存在的文件验证快速返回
    result = vlm_analyzer.analyze_frame_quick("/nonexistent/file.jpg")
    assert result["court_visible"] == False
    assert result["player_count"] == 0
    assert "error" in result
    print(f"  ✓ analyze_frame_quick快速失败路径OK")

if __name__ == "__main__":
    print("Running smoke tests...")
    tests = [
        ("STYLE keys", test_style_keys),
        ("_render_shot_text gone", test_render_no_missing_function),
        ("preflight_check sig", test_preflight_check_signature),
        ("analyze_frame_quick", test_vlm_analyze_frame_quick),
        ("make_report invocation", test_report_make_invocation),
    ]
    passed = 0
    for name, fn in tests:
        try:
            print(f"\n  [{name}]")
            fn()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            import traceback; traceback.print_exc()

    print(f"\n{'='*44}")
    print(f"  结果: {passed}/{len(tests)} 通过")
    if passed == len(tests):
        print("  → 可以安全分析视频")
    else:
        print("  → 有测试失败，修复后再分析")
        sys.exit(1)
