S3 第 1 轮：溢出行为证据确凿（recorder-status.json: seq=113, buffered_count=60=上限, dropped=53），但判读只看导出 ack（与 taskkill 清理竞态失败）→ 误报 false。判读已改为以状态文件兜底。
