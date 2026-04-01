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

parser = argparse.ArgumentParser(description="反汇编 asm")
parser.add_argument("-a", type=str, help="asm 输入目录", default="asm_output")
parser.add_argument("-o", type=str, help="cpp 输出目录", default="cpp_output")
parser.add_argument("-api", type=str, help="OpenAI URL", default="http://127.0.0.1:7001/v1")
parser.add_argument("-key", type=str, help="Api Key", default="sk-no-key-required")
parser.add_argument("-model", type=str, help="Model Name", default="llama-3.1-8b-instruct")
parser.add_argument("-sys", type=str, help="system prompt", default="source_system_prompt.txt")
args = parser.parse_args()

# ========================== 配置区 ==========================
ASM_DIR = args.a
OUTPUT_DIR = args.o
MAX_RETRIES = 5

BASE_URL = args.api
API_KEY = args.key
MODEL_NAME = args.model

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
console = Console()

# ===========================================================

os.makedirs(OUTPUT_DIR, exist_ok=True)


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
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def read_asm_file(asm_path: Path):
    with open(asm_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


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

    reasoning_buf: list[str] = []
    response_buf:  list[str] = []

    console = Console()
    reas_i = -150

    def build_display() -> Text:
        nonlocal reas_i
        t = Text()
        if reasoning_buf:
            t.append("💭 思考中…\n", style="bold yellow")
            t.append("".join(reasoning_buf[reas_i:]), style="dim yellow")
            t.append("\n")
        if response_buf:
            t.append("🤖 回答\n", style="bold cyan")
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

        return True, "".join(reasoning_buf), "".join(response_buf)

    except Exception as exc:
        console.print(f"[red]请求失败：{exc}[/red]")
        return False, "", ""


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
      messages.append({"role": "user", "content": f"\n\n上次编译错误:\n{error_feedback}\n请修复并输出完整可编译代码。"})

    succ, think, resp = chat_with_stream(BASE_URL, API_KEY, messages)
    return extract_code(resp)
    


def compile_cc_file(cc_path: Path):
    output_exe = cc_path.with_suffix(".exe")
    cmd = ["g++", "-o", str(output_exe), "-std=c++17", "-O2", "-Wall", "-Wno-unused-variable", str(cc_path)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="ignore")
        if result.returncode == 0:
            return True, ""
        else:
            return False, result.stderr.strip() or result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "编译超时（60秒）"
    except FileNotFoundError:
        return False, "错误：未找到 g++，请确保 GCC 已安装并加入 PATH"


def compile_to_object(cc_path: Path):
    """只编译生成 .o 文件，不链接"""
    output_obj = cc_path.with_suffix(".o")
    cmd = [
        "gcc", "-c",                    # ← 关键：只编译不链接
        "-std=c++17",
        "-O2",
        "-Wall",
        "-Wno-unused-variable",
        "-Wno-unused-but-set-variable",
        str(cc_path),
        "-o", str(output_obj)
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="ignore"
        )

        if result.returncode == 0:
            return True, str(output_obj), ""
        else:
            return False, None, (result.stderr.strip() or result.stdout.strip())
    except subprocess.TimeoutExpired:
        return False, None, "编译超时（60秒）"
    except FileNotFoundError:
        return False, None, "错误：未找到 gcc/g++，请确保 GCC 已安装并加入 PATH"
        

def process_single_asm(asm_path: Path):
    func_name = asm_path.stem
    cc_path = Path(OUTPUT_DIR) / f"{func_name}.cc"
    compile_error_file = cc_path.with_suffix(".compile_error.txt")

    console.print(f"\n[bold cyan]正在处理函数:[/bold cyan] {func_name}")

    asm_content = read_asm_file(asm_path)
    error_feedback = None
    cpp_code = None
    
    if cc_path.exists() and cc_path.with_suffix(".o").exists():
      return True

    for attempt in range(1, MAX_RETRIES + 1):
        console.print(f"[yellow]第 {attempt} 次尝试生成代码...[/yellow]")
        
        # 流式生成 + 实时显示（限制5行左右）
        cpp_code = stream_generate_cpp(asm_content, func_name, error_feedback, cpp_code)
        # 写入文件
        with open(cc_path, "w", encoding="utf-8") as f:
            f.write(cpp_code)

        # 编译
        console.print("[yellow]正在编译...[/yellow]")
        success, outfile, error_msg = compile_to_object(cc_path)

        if success:
            console.print(f"[bold green]✓ 编译成功！[/bold green] → {cc_path.name}")
            if compile_error_file.exists():
                compile_error_file.unlink()
            return True
        else:
            console.print(f"[bold red]✗ 第 {attempt} 次编译失败[/bold red]")
            with open(compile_error_file, "w", encoding="utf-8") as f:
                f.write(error_msg)
            '''
            if attempt == MAX_RETRIES:
                console.print("[red]已达到最大重试次数，跳过该函数。[/red]")
                return False '''

            # 显示编译错误（清晰回显）
            console.print(Panel(error_msg[:2500], title="编译错误", border_style="red", style="red"))
            error_feedback = error_msg[:2500]   # 反馈给下一次生成
            console.print("[dim]错误已反馈给 AI，正在尝试修复...[/dim]")

    return False


def main():
    asm_files = sorted(Path(ASM_DIR).glob("*.asm"))
    if not asm_files:
        console.print("[red]未找到任何 .asm 文件！[/red]")
        return

    console.print(f"[bold]找到 {len(asm_files)} 个 asm 文件，开始处理...[/bold]\n")

    success_count = 0
    with tqdm(asm_files, desc="整体进度", colour="cyan") as pbar:
        for asm_path in pbar:
            if process_single_asm(asm_path):
                success_count += 1
            pbar.set_postfix({"成功": f"{success_count}/{len(asm_files)}"})

    console.print(f"\n[bold green]全部处理完成！成功编译 {success_count}/{len(asm_files)} 个函数。[/bold green]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]程序被用户中断。[/yellow]")