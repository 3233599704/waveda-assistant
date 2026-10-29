"""审计知识库图片引用：找出哪些能找到，哪些缺失"""
import os, re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

# 1. 构建图片索引（文件名 → 路径）
img_index = {}
for root, dirs, files in os.walk("wavEDA_docs/helpHtml"):
    for f in files:
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg")):
            img_index[f] = os.path.join(root, f).replace(os.sep, "/")

print(f"仓库实际图片数: {len(img_index)}")

# 2. 提取所有 md 文件的图片引用
refs = []
for root, dirs, files in os.walk("knowledge_base"):
    for f in files:
        if f.endswith(".md"):
            fpath = os.path.join(root, f)
            with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            found = re.findall(r"`\.?/([^`]+\.(?:png|jpg|jpeg|gif|svg))`", content)
            for img_path in found:
                basename = os.path.basename(img_path)
                refs.append((fpath.replace(os.sep, "/"), img_path, basename))

print(f"图片引用总数: {len(refs)}")

# 3. 分类
found_refs = [(fp, ip, bn) for fp, ip, bn in refs if bn in img_index]
missing_refs = [(fp, ip, bn) for fp, ip, bn in refs if bn not in img_index]

print(f"能找到: {len(found_refs)}")
print(f"缺失:   {len(missing_refs)}")

# 4. 缺失明细
if missing_refs:
    missing_files = Counter(b for _, _, b in missing_refs)
    print(f"\n缺失图片文件名 (去重 {len(missing_files)} 个):")
    for name, count in missing_files.most_common(30):
        print(f"  {name} ({count}次)")

    # 按目录统计
    dirs_missing = Counter()
    for fp, _, _ in missing_refs:
        parts = fp.split("/")
        for p in parts:
            if p.startswith("0") or p == "knowledge_base":
                if p != "knowledge_base":
                    dirs_missing[p] += 1
    print(f"\n缺失引用所在目录:")
    for d, c in dirs_missing.most_common():
        print(f"  {d}: {c}个")

# 5. 可找到的明细（按目录）
if found_refs:
    dirs_found = Counter()
    for fp, _, _ in found_refs:
        parts = fp.split("/")
        for p in parts:
            if p.startswith("0") or p == "knowledge_base":
                if p != "knowledge_base":
                    dirs_found[p] += 1
    print(f"\n可找到的引用所在目录:")
    for d, c in dirs_found.most_common():
        print(f"  {d}: {c}个")
