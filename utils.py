import os
import subprocess
import re
import sys
import signal
import argparse
from pathlib import Path
from tqdm import tqdm
from openai import OpenAI
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich import box
from collections import Counter
import json
import networkx as nx
from networkx.readwrite import json_graph
from collections import defaultdict
from typing import Callable

console = Console()


def load_token(file=".token"):
  try:
    with open(file, 'r', encoding='utf8') as f:
      return int(f.read())
  except Exception:
    return 0
    
total_token = load_token()

def save_token(file=".token"):
  with open(file, 'w', encoding='utf8') as f:
    f.write(str(total_token))


def load_and_traverse_callgraph(
    json_path: str,
    callback: Callable[[str, str, int, int, list[str]], None],
):
    """
    callback 签名: (node_id, func_name, current, total, deps)
      - node_id:   图中节点 id
      - func_name: 函数名（label）
      - current:   当前第几个（1-based）
      - total:     总节点数
      - deps:      该函数直接调用的函数名列表（调用时已全部处理完毕）
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    graph: nx.MultiDiGraph = json_graph.node_link_graph(
        data, directed=True, multigraph=True
    )

    def get_name(node) -> str:
        return graph.nodes[node].get("label", str(node))

    def get_deps(node) -> list[str]:
        # 出边邻居 = 该函数直接调用的函数
        return [get_name(callee) for callee in graph.successors(node)]

    # 计算遍历顺序
    if nx.is_directed_acyclic_graph(graph):
        order = list(reversed(list(nx.topological_sort(graph))))
    else:
        scc_graph = nx.condensation(graph)
        scc_map = scc_graph.graph["mapping"]
        order = []
        for scc_id in reversed(list(nx.topological_sort(scc_graph))):
            members = [n for n, s in scc_map.items() if s == scc_id]
            order.extend(members)

    total = len(order)
    for current, node in enumerate(order, start=1):
        callback(node, get_name(node), current, total, get_deps(node))
        

def repetition_score(tokens, n=3):
    if len(tokens) < 10:
      return 0
    ngrams = [tuple(tokens[i:i+n]) for i in range(len(tokens)-n)]
    counter = Counter(ngrams)
    most_common = counter.most_common(1)
    if not most_common:
        return 0
    return most_common[0][1] / len(ngrams)
    

def extract_code(text: str, lang_hint: str = "") -> str:
    """
    从 AI 返回文本中提取代码块。
    
    优先提取指定语言的围栏块，其次任意围栏块，
    最后 fallback 到全文（去首尾空白）。
    """
    # 匹配 ```lang ... ``` 或 ``` ... ```
    pattern = r"```(?:[\w+\-]*)?\s*\n?(.*?)```"
    blocks = re.findall(pattern, text, re.DOTALL)

    if not blocks:
        return text.strip()

    if lang_hint:
        # 找带指定语言标签的块
        tagged = re.findall(
            rf"```{re.escape(lang_hint)}\s*\n?(.*?)```",
            text, re.DOTALL | re.IGNORECASE
        )
        if tagged:
            return tagged[0].strip()

    # 返回最长的块（通常是主体代码）
    return max(blocks, key=len).strip()
    

# 优雅处理 Ctrl+C
def signal_handler(sig, frame):
    console.print("\n[yellow]用户中断 (Ctrl+C)，正在退出...[/yellow]")
    save_token()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


def chat_with_stream(
    base_url: str,
    api_key: str,
    messages: list[dict],
) -> tuple[bool, str, str]:
    """
    流式调用 OpenAI 兼容 API，实时回显思考和应答，完成后清除回显。

    Args:
        base_url: API 基础 URL
        api_key:  API 密钥
        messages: 消息数组，格式同 OpenAI messages

    Returns:
        (success, reasoning_content, response_content)
    """
    client = OpenAI(base_url=base_url, api_key=api_key)
    global total_token

    reasoning_buf: list[str] = []
    response_buf:  list[str] = []

    console = Console()
    reas_i = -150

    def build_display() -> Text:
        nonlocal reas_i
        t = Text()
        if reasoning_buf:
            t.append(f"💭 思考中… {len(reasoning_buf)} - {total_token}\n", style="bold yellow")
            t.append("".join(reasoning_buf[reas_i:]), style="dim yellow")
            t.append("\n")
        if response_buf:
            t.append(f"🤖 回答 {len(response_buf)} - {total_token}\n", style="bold cyan")
            t.append("".join(response_buf[-200:]), style="cyan")
            if reas_i < -10:
              reas_i = reas_i + 2
        return t

    try:
        stream = client.chat.completions.create(
            model="deepseek-reasoner",   # 换成实际模型名
            messages=messages,
            stream=True,
        )

        with Live(
            build_display(),
            console=console,
            refresh_per_second=5,
            transient=True,     # ← 完成后自动清除
        ) as live:
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # reasoning_content —— DeepSeek-R1 / o1 系列思考块
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_buf.append(rc)

                # content —— 正式回答
                if delta.content:
                    response_buf.append(delta.content)

                live.update(build_display())
        rea = "".join(reasoning_buf)
        res = "".join(response_buf)
        total_token = total_token + len(rea) + len(res)
        return True, rea, res

    except Exception as exc:
        console.print(f"[red]请求失败：{exc}[/red]")
        return False, "", ""
    finally:
        save_token()


def stream_generate_cpp(asm_content: str, func_name: str, error_feedback: str = None, cpp_code = None):
    with open(args.sys, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"//函数名: {func_name}\n\n{asm_content}"}
    ]
    
    if cpp_code:
      messages.append({'role':'assistant', 'content': f"上次生成的c/c++代码:{cpp_code}"})
    
    if error_feedback:
      messages.append({"role": "user", "content": f"\n\n上次逻辑分析错误:\n{error_feedback}\n请修复并输出完整可逻辑分析代码。"})

    succ, think, resp = chat_with_stream(BASE_URL, API_KEY, messages)
    return resp +"\n\n# 思考过程\n\n"+ think
    

def sanitize_filename(name):
    """处理 Windows 非法文件名字符"""
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def parse_addr(asm):
  match = re.search(r'Address:\s*(0x[0-9a-fA-F]+)', asm)
  if match:
      return int(match.group(1), 16)
  return None