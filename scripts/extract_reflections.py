import os
import sys
import sqlite3
import glob
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"
REVIEWS_DIR = ROOT / "docs" / "reviews"

def extract_and_save_reflections():
    print(f"=== 开始提取复盘手工填写项 ===")
    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS review_reflections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        topic TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, topic)
    )
    ''')
    
    md_files = glob.glob(str(REVIEWS_DIR / "*.md"))
    saved_count = 0
    
    for md_file in md_files:
        filename = Path(md_file).name
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
        if not date_match:
            continue
        date_str = date_match.group(1)
        
        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        print(f"处理文件: {filename}")
            
        # 宽泛一点的匹配，匹配包含"思考"、"复盘"、"反思"、"手工"的标题
        sections = re.split(r'\n## ', '\n' + content)
        reflection_text = ""
        for section in sections:
            if re.match(r'(?:.*思考.*|.*复盘.*|.*反思.*|.*手工.*)', section.split('\n')[0], re.IGNORECASE):
                # 排除像 "每日复盘" 这样的一级标题或者没有子标题的区域
                if "###" in section:
                    reflection_text += section + "\n"
                
        if reflection_text:
            topics = re.finditer(r'### ([^\n]+)\n(.*?)(?=\n### |$)', reflection_text, re.DOTALL)
            
            for topic_match in topics:
                topic = topic_match.group(1).strip()
                topic_content = topic_match.group(2).strip()
                
                if topic_content and not topic_content.startswith(('（在此填写', '(在此填写', '在此填写', '- [ ]')):
                    cursor.execute('''
                    INSERT INTO review_reflections (date, topic, content)
                    VALUES (?, ?, ?)
                    ON CONFLICT(date, topic) DO UPDATE SET content=excluded.content, created_at=CURRENT_TIMESTAMP
                    ''', (date_str, topic, topic_content))
                    saved_count += cursor.rowcount
                    print(f"[{date_str}] 提取到手工思考: {topic}")
        
        # 补充：提取未勾选的复盘要点选项中用户修改的内容
        review_points = re.search(r'\*\*思考问题\*\*.*?：\n(.*?)(?=\n\n|\n---|## |$)', content, re.DOTALL)
        if review_points:
            points_text = review_points.group(1)
            # 例如: - [ ] 信号给出 SELL 但没卖的，事后看对不对？ -> 确实不对
            custom_notes = []
            for line in points_text.split('\n'):
                if line.strip().startswith('- [ ]') or line.strip().startswith('- [x]') or line.strip().startswith('- [X]'):
                    # 如果这行不仅仅是模板问题，还包含了额外的文字，提取出来
                    if '？' in line:
                        parts = line.split('？')
                        if len(parts) > 1 and parts[1].strip():
                            custom_notes.append(line.strip())
                    elif '?' in line:
                        parts = line.split('?')
                        if len(parts) > 1 and parts[1].strip():
                            custom_notes.append(line.strip())
            
            if custom_notes:
                cursor.execute('''
                INSERT INTO review_reflections (date, topic, content)
                VALUES (?, ?, ?)
                ON CONFLICT(date, topic) DO UPDATE SET content=excluded.content, created_at=CURRENT_TIMESTAMP
                ''', (date_str, '复盘要点回答', '\n'.join(custom_notes)))
                saved_count += cursor.rowcount
                print(f"[{date_str}] 提取到复盘要点回答")
    
    conn.commit()
    conn.close()
    
    print(f"=== 提取完成，共保存/更新 {saved_count} 条复盘思考 ===")

if __name__ == "__main__":
    extract_and_save_reflections()
