/** 日期/时长格式化（对齐 Web read/library 页的展示规则） */

/** yyyy-mm-dd；解析失败原样返回（后端日期偶有非标准串） */
export function formatDate(dateStr?: string): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return y + '-' + m + '-' + day;
}

/** 秒 → m:ss / h:mm:ss（章节时间戳、转录行时间） */
export function formatPlayerTime(secs: number): string {
  const s = Math.max(0, Math.floor(secs || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + sec;
  return m + ':' + sec;
}

/** 秒 → X 小时 Y 分钟 / X 分钟（音频总时长） */
export function formatDuration(seconds: number): string {
  const s = Math.floor(seconds || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return m > 0 ? h + ' 小时 ' + m + ' 分钟' : h + ' 小时';
  if (m > 0) return m + ' 分钟';
  return s + ' 秒';
}

/** 分钟 → 不到 1 分钟 / X 分钟 / X 小时 Y 分钟（阅读时长） */
export function formatReadingTime(minutes: number): string {
  const m = Math.floor(minutes || 0);
  if (m <= 0) return '不到 1 分钟';
  if (m < 60) return m + ' 分钟';
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest > 0 ? h + ' 小时 ' + rest + ' 分钟' : h + ' 小时';
}
