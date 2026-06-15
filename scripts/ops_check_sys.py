import psutil

print('=== 磁盘使用率 ===')
disk_ok = True
for part in psutil.disk_partitions():
    try:
        usage = psutil.disk_usage(part.mountpoint)
        pct = usage.percent
        status = 'OK' if pct < 80 else 'WARN'
        if pct >= 80:
            disk_ok = False
        print(status + ' ' + str(part.device) + ' (' + str(part.mountpoint) + '): ' + str(pct) + '% used, ' + str(round(usage.free/1e9, 1)) + 'GB free')
    except:
        pass

print()
print('=== 内存使用率 ===')
mem = psutil.virtual_memory()
mem_pct = mem.percent
mem_ok = mem_pct < 85
status = 'OK' if mem_ok else 'WARN'
print(status + ' Memory: ' + str(mem_pct) + '% used, ' + str(round(mem.available/1e9, 1)) + 'GB free / ' + str(round(mem.total/1e9, 1)) + 'GB total')

print()
print('=== CPU ===')
cpu_pct = psutil.cpu_percent(interval=1)
print('CPU: ' + str(cpu_pct) + '%')

print()
print('=== 系统资源总结 ===')
print('Disk: ' + ('OK - 正常' if disk_ok else 'WARN - 超过80%'))
print('Memory: ' + ('OK - 正常' if mem_ok else 'WARN - 超过85%'))
