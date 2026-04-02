import os
import sys
import argparse
import re
import base64
from pathlib import Path
from rich.console import Console
from utils import \
    load_and_traverse_callgraph, \
    parse_addr

console = Console()
parser = argparse.ArgumentParser(description="生成 rizin 脚本")
parser.add_argument("-m", type=str, help="md 输入目录", default="asm_output")
parser.add_argument("-a", type=str, help="asm 输入目录")
parser.add_argument("-g", type=str, help="graph json file", default="callgraph.json")
parser.add_argument("-o", type=str, help="save rizin file name")
args = parser.parse_args()
GRAPH_JSON = args.g
INPUT_DIR = args.m
SAVE_FILE = args.o
ASM_DIR = args.a
save = None
not_found = 0


def make_ccu_command(text: str, address: int) -> str:
    """
    安全地生成 rizin CCu 命令。
    CCu 接受 base64 编码的 UTF-8 字符串。
    """
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"CCu base64:{encoded} @ 0x{address:x}"


def process_node(node, name, c, t, deps):
  global not_found
  mdf = Path(INPUT_DIR) / f"{name}.asm.md"
  asmf = Path(ASM_DIR) / f"{name}.asm"
  if not mdf.exists() or not asmf.exists():
    console.print(f"Error 文件不存在 {name}, {c}/{t}", style="bold red")
    not_found += 1
    return
  
  console.print(f"正在处理 {name}, {c}/{t}  ({c/t*100:6.2f}%)")

  with open(asmf, 'r', encoding='utf-8') as asm:    
    addr = parse_addr(asm.read())
    with open(mdf, 'r', encoding="utf-8") as md:
      comm = md.read();
      cmd = make_ccu_command(comm, addr)
      save.write(cmd)
      save.write('\n')
  return


def main():
  if os.path.isfile(GRAPH_JSON):
    load_and_traverse_callgraph(GRAPH_JSON, process_node)
  else:
    console.print(f"\n[bold green]无法打开: {GRAPH_JSON}, (用 dasm.py 生成汇编文件)")


if __name__ == "__main__":
  try:
      if not SAVE_FILE:
        SAVE_FILE = GRAPH_JSON +".rizin"
      if not ASM_DIR:
        ASM_DIR = INPUT_DIR
      save = open(SAVE_FILE, 'w', encoding="utf-8")
      main()
      console.print("All Done")
      if not_found > 0:
        console.print(f" - {not_found} 个文件失败", style="bold yellow")
  except KeyboardInterrupt:
      console.print("\n[yellow]程序被用户中断。[/yellow]")
  finally:
      save.close()