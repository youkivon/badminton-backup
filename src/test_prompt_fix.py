# -*- coding: utf-8 -*-
"""
三次修复prompt测试：验证8分100%集中问题是否解决
只改prompt，不改代码逻辑
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))

from vlm_analyzer_v2 import batch_analyze_with_ball
from collections import Counter

FRAMES_DIR = "/Users/youqifang/Desktop/小程序/players/W2D1二次修复/frames/dbf21e02323a"
CACHE_PATH = "/Users/youqifang/Desktop/小程序/players/W2D1三次修复_cache.json"

def main():
    frame_paths = sorted([
        os.path.join(FRAMES_DIR, f) 
        for f in os.listdir(FRAMES_DIR) if f.endswith('.jpg')
    ])
    print(f"找到 {len(frame_paths)} 帧")
    
    # 运行VLM分析
    print("启动VLM分析...")
    results = batch_analyze_with_ball(frame_paths)
    print(f"VLM分析完成，返回 {len(results)} 个结果")
    
    # 保存原始结果
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"原始结果已保存: {CACHE_PATH}")
    
    # 过滤并统计
    bad_labels = {"无法判断", "unable to determine", "unknown", "", "SKIP"}
    valid = [r for r in results 
             if r.get("action_type", "") not in bad_labels 
             and r.get("quality_rating", 0) > 0]
    print(f"\n有效击球: {len(valid)}/{len(results)}")
    
    if not valid:
        print("无有效击球，检查VLM输出")
        # 打印前3个结果
        for r in results[:3]:
            print(f"  {r.get('frame_file')}: type={r.get('action_type')}, rating={r.get('quality_rating')}, raw[:100]={r.get('raw_response','')[:100]}")
        return
    
    # 统计评分分布
    ratings = [r['quality_rating'] for r in valid]
    rating_dist = Counter(ratings)
    print(f"\n综合评分分布:")
    for score in sorted(rating_dist.keys()):
        print(f"  {score}分: {rating_dist[score]}帧 ({rating_dist[score]*100//len(valid)}%)")
    
    avg_rating = sum(ratings) / len(ratings)
    print(f"平均分: {avg_rating:.2f}")
    
    # 统计各维度
    dims = ['发力链', '闪腕', '步伐', '拍面控制', '整体协调']
    print(f"\n各维度评分:")
    for dim in dims:
        vals = [r[dim] for r in valid if r.get(dim, 0) > 0]
        if vals:
            avg = sum(vals) / len(vals)
            dist = Counter(vals)
            print(f"  {dim}: 平均{avg:.1f}, 分布={dict(sorted(dist.items()))}")
    
    # 统计主要问题
    all_errors = []
    for r in valid:
        for e in r.get('errors', []):
            if e and e.lower() not in ('none', '无', 'n/a', 'n/a-'):
                all_errors.append(e)
    error_dist = Counter(all_errors)
    print(f"\n主要问题分布(前5):")
    for err, cnt in error_dist.most_common(5):
        print(f"  {err[:60]}: {cnt}")
    
    # E9专项统计
    e9_count = sum(1 for e in all_errors if 'E9' in str(e))
    print(f"\nE9(随挥不完整)出现: {e9_count}/{len(valid)}帧")
    
    # 检查是否有7分和9分
    has_7 = any(r == 7 for r in ratings)
    has_8 = any(r == 8 for r in ratings)
    has_9 = any(r == 9 for r in ratings)
    print(f"\n7分存在: {has_7}, 8分存在: {has_8}, 9分存在: {has_9}")
    
    if has_7 or has_9:
        print("✅ 评分多样化问题已解决!")
    else:
        print("❌ 仍全部为8分，需要进一步调优")

if __name__ == "__main__":
    main()