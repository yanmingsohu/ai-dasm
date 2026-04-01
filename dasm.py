import angr
import os
import re
import argparse

parser = argparse.ArgumentParser(description="反汇编exe")
parser.add_argument("-f", type=str, help="文件名")
parser.add_argument("-o", type=str, default="asm_output", help="输出目录")
args = parser.parse_args()

infilename = args.f
OUTPUT_DIR = os.path.join(os.path.dirname(args.f), args.o)


def sanitize_filename(name):
    """处理 Windows 非法文件名字符"""
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def dump_function_cfg(func, cfg):
    """
    正确遍历函数的所有基本块并按地址顺序输出汇编
    """
    result = []

    # 获取该函数的所有节点（基本块）
    function_nodes = sorted(
        (node for node in cfg.graph.nodes() if node.function_address == func.addr),
        key=lambda n: n.addr
    )

    for node in function_nodes:
        block = node.block
        if block is None:
            continue

        # 输出块的汇编（使用 capstone）
        for insn in block.capstone.insns:
            result.append(f"{hex(insn.address)}:\t{insn.mnemonic}\t{insn.op_str}")

        # 可选：块之间加空行或注释，便于阅读
        result.append("")

    return "\n".join(result)


def main(binary_path):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("正在加载二进制文件并生成 CFG（可能需要一些时间）...")
    proj = angr.Project(binary_path, auto_load_libs=False)

    # normalize=True 能让基本块更规整，推荐保留
    cfg = proj.analyses.CFGFast(normalize=True, show_progressbar=True)

    print(f"共发现 {len(cfg.kb.functions)} 个函数，开始导出...")

    for func_addr, func in cfg.kb.functions.items():
        func_name = func.name or f"sub_{func_addr:x}"
        func_name = sanitize_filename(func_name)

        file_path = os.path.join(OUTPUT_DIR, f"{func_name}.asm")

        asm_text = dump_function_cfg(func, cfg)

        if not asm_text.strip():
            continue

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"; Function: {func_name}\n")
            f.write(f"; Address: {hex(func_addr)}\n")
            f.write(f"; Size: {func.size} bytes\n\n")
            f.write(asm_text)

        # 可选：每导出 100 个函数打印一次进度
        if (len(cfg.kb.functions) > 100 and 
            list(cfg.kb.functions.keys()).index(func_addr) % 100 == 0):
            print(f"已处理 {list(cfg.kb.functions.keys()).index(func_addr)} / {len(cfg.kb.functions)} 个函数...")

    print("所有函数 ASM 导出完成！")


if __name__ == "__main__":
    main(infilename)