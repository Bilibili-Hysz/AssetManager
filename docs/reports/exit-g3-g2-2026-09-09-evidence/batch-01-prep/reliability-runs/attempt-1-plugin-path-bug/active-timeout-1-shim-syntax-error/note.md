S2 第 1 轮：extras 行与 return d 拼接缺真实换行 → sitecustomize SyntaxError → 驱动跑真实 exe（无插件）正常 PASS，但挂起注入未生效，超时未被模拟。控制器 _extras_lines 返回值已补末尾换行。
