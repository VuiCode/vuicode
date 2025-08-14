

import os, yaml
from dotenv import load_dotenv
from datetime import datetime, timezone
from pathlib import Path
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

TOPIC = input("Topic (e.g., Chatbot Flask + React): ").strip()
slug = TOPIC.lower().replace(" ","-").replace("+","plus")
base = Path("content")
(b := base/"blog"/slug).mkdir(parents=True, exist_ok=True)
(v := base/"video"/slug).mkdir(parents=True, exist_ok=True)

front = {
  "title_en": TOPIC,
  "title_vi": f"Cách xây {TOPIC}",
  "tags": ["vuicode","tutorial","simple-code","clear-results"],
  "created": datetime.now(timezone.utc).isoformat()
}
with open(b/"meta.yaml","w") as f: yaml.safe_dump(front,f)

def gen(system, prompt):
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"system","content":system},
                  {"role":"user","content":prompt}],
        temperature=0.4,
    )
    return r.choices[0].message.content

md_en = gen(
  "You are VuiCode Writer. Write a clear, beginner-friendly tech blog with headings, code blocks, and a 'Clear Result' section first.",
  f"Write a markdown blog post (800-1200 words) about {TOPIC}. Stack: Flask backend API + React frontend. Show demo first, then simple code, then details. Include code blocks."
)
md_vi = gen(
  "Bạn là VuiCode Writer. Viết blog tiếng Việt dễ hiểu, có tiêu đề phụ, code block, phần 'Kết quả rõ ràng' ở đầu.",
  f"Viết bài blog markdown (800–1200 chữ) về {TOPIC}. Stack: Flask API + React. Ưu tiên đơn giản, ai cũng làm được."
)
with open(b/"post.en.md", "w", encoding="utf-8") as f:
  f.write(md_en)
with open(b/"post.vi.md", "w", encoding="utf-8") as f:
  f.write(md_vi)

script = gen(
  "You are VuiCode Video Scriptwriter. Create a 5-min script aligned to VuiCode structure.",
  f"Create a YouTube script for {TOPIC} following this outline: 1 intro(5s), 2 title, 3 clear result demo, 4 simple code, 5 architecture, 6 backend details, 7 frontend details, 8 run fullstack, 9 outro(5s). Provide time-codes and on-screen text."
)
with open(v/"script.md", "w", encoding="utf-8") as f:
  f.write(script)

print(f"✅ Generated: {b}/post.en.md, post.vi.md and {v}/script.md")
