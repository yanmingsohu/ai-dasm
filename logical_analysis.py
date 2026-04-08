import os
import sys
import argparse
from pathlib import Path
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
import json
from utils import \
    load_and_traverse_callgraph, \
    chat_with_stream

parser = argparse.ArgumentParser(description="反汇编 asm")
parser.add_argument("-a", type=str, help="asm 输入目录", default="asm_output")
parser.add_argument("-o", type=str, help="输出目录", default="asm_output")
parser.add_argument("-api", type=str, help="OpenAI URL", default="http://127.0.0.1:7001/v1")
parser.add_argument("-key", type=str, help="Api Key", default="sk-no-key-required")
parser.add_argument("-model", type=str, help="Model Name", default="llama-3.1-8b-instruct")
parser.add_argument("-sys", type=str, help="system prompt", default="logical_analysis.txt")
parser.add_argument("-g", type=str, help="graph json file", default="callgraph.json")
args = parser.parse_args()

# ========================== 配置区 ==========================
ASM_DIR = args.a
OUTPUT_DIR = args.o
MAX_RETRIES = 5
GRAPH_JSON = args.g

BASE_URL = args.api
API_KEY = args.key
MODEL_NAME = args.model

console = Console()

# ===========================================================

def process_node(node, name, c, t, deps):
    save_file = Path(OUTPUT_DIR) / f"{name}.asm.md"
    if save_file.exists():
      console.print(f"跳过 {name}, {c}/{t}")
      return
      
    console.print(f"正在处理 {name}, {c}/{t}  ({c/t*100:6.2f}%) - {deps}")
    asm_file = Path(ASM_DIR) / f"{name}.asm"
    if not asm_file.exists():
      console.print(f"    - 文件不存在 {asm_file}", style="bold red")
      return
    
    with open(args.sys, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    messages = [
        {"role": "system", "content": system_prompt},
    ]
    
    with open(asm_file, "r", encoding="utf-8") as f:
        messages.append({"role": "user", "content": f";函数名: {name} 汇编代码:\n{f.read()}"})
        
    cc_file = Path(ASM_DIR) / f"{name}.asm.c"
    if cc_file.exists():
      with open(cc_file, "r", encoding="utf-8") as f:
          messages.append({"role": "user", "content": f"//函数名: {name} 反汇编c代码:\n{f.read()}"})
        
    for dname in deps:
      if dname != name:
        dep_file = Path(OUTPUT_DIR) / f"{dname}.asm.md"
        if not dep_file.exists():
          console.print(f"    - 依赖文件不存在 {dep_file}", style="yellow")
          continue
        with open(dep_file, "r", encoding="utf-8") as f:
          messages.append({"role": "user", "content": f"依赖函数名: {dname} 说明:\n{f.read()}"})

    succ, think, resp = chat_with_stream(BASE_URL, API_KEY, messages)
    if succ and resp and len(resp)>0:
      with open(save_file, "w", encoding="utf-8") as f:
        f.write(resp)
    
    return
    

def main():
    if os.path.isfile(GRAPH_JSON):
      os.makedirs(OUTPUT_DIR, exist_ok=True)
      load_and_traverse_callgraph(GRAPH_JSON, process_node)
    else:
      console.print(f"\n[bold green]无法打开: {GRAPH_JSON}, (用 dasm.py 生成汇编文件)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]程序被用户中断。[/yellow]")