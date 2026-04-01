# 利用 AI 进行反汇编工程

## 反汇编

```sh
python dasm.py \
  -f [EXE文件路径] \
  -o [文件输出目录]
```

该命令会读取 EXE 并在输出目录生成 `.c`/`.asm` 文件,
在 EXE 同级目录生成 `.callgraph.json` 函数调用图文件.


## 分析

```sh
python logical_analysis.py \
  -a [通常是dasm.py的输出目录, 从中读取 .c/.asm 文件] \
  -o [应该与 -a 参数相同, 输出分析报告 .md] \
  -g [.callgraph.json 文件路径] \
  -sys [系统提示词文件] \
  -api [OpenAI api like 接口URL] \
  -key [api 密钥] \
  -model [AI模型名称]
```

该命令调用大模型对生成的函数文件进行分析并生成报告文件.


## 生成 C 代码

```sh
python source.py \
  -a [通常是dasm.py的输出目录, 从中读取 .asm 文件] \
  -o [生成 .c/.o 文件的目录] \
  -sys [系统提示词文件] \
  -api [OpenAI api like 接口URL] \
  -key [api 密钥] \
  -model [AI模型名称]
```

该命令读取 `.asm` 文件, 然后用 AI 编写对应的 C 代码文件, 然后对该文件进行 gcc 编译生成 .o 文件,
只能保证编译通过, 逻辑可能是错误的.

[该功能未完成], 需要导出所有全局变量到一个 .c 文件并进行编译, 然后链接所有 .o 文件.