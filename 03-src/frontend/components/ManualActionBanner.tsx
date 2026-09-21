'use client';

import { useState } from 'react';
import { AlertTriangle, Loader2, Play } from 'lucide-react';

/**
 * 人工介入横幅（橙色警示，区别于红色错误）。
 *
 * 适用：job 因 error_stage === 'manual_action' 失败 —— 即"重试一万次也一样，
 * 必须等用户做完某个外部动作"。当前唯一来源是**微信视频号**：媒体来自本机
 * 2022 端口上一个由用户手动播放过的微信 PC 端页面连接，worker 无法自己制造。
 *
 * 与 PipelineBar 的分工：PipelineBar 说明"卡在哪一步"，本组件说明"你要做什么"。
 * error_message 由 worker 直接写好（action｜detail），这里原样渲染，不做二次映射
 * —— 提示文案的可执行性由能拿到上下文的那一侧负责。
 */
export default function ManualActionBanner({
  message,
  onRetry,
  retrying = false,
}: {
  message?: string | null;
  /** 「我已播放，重试」：传 from_step 给既有 retry 接口 */
  onRetry?: () => void;
  retrying?: boolean;
}) {
  const [showHelp, setShowHelp] = useState(false);

  return (
    <div className="mb-4 rounded-2xl border border-[#ff9500]/40 bg-[#ff9500]/[0.08] overflow-hidden">
      <div className="flex items-start gap-3 px-4 py-3">
        <AlertTriangle size={18} className="text-[#e68600] shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-[13.5px] font-semibold text-[#8a5200]">需要你操作一下</p>
          {message && (
            <p className="mt-1 text-[12.5px] leading-[1.6] text-[#8a5200]/90 break-words">
              {message}
            </p>
          )}
          <button
            type="button"
            onClick={() => setShowHelp((v) => !v)}
            className="mt-1.5 text-[11.5px] text-[#8a5200]/70 hover:text-[#8a5200] underline underline-offset-2"
          >
            {showHelp ? '收起说明' : '第一次遇到？看这里'}
          </button>
        </div>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            disabled={retrying}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                       bg-[#ff9500] text-white text-[12.5px] font-medium
                       hover:bg-[#e68600] disabled:opacity-60 transition-colors"
          >
            {retrying ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            我已播放，重试
          </button>
        )}
      </div>

      {showHelp && (
        <div className="px-4 pb-3 pt-0 text-[11.5px] leading-[1.9] text-[#8a5200]/80 border-t border-[#ff9500]/20 mt-1">
          <p className="pt-2 font-medium text-[#8a5200]">视频号为什么需要你播放一次？</p>
          <p>
            视频号没有公开可下载的媒体地址，媒体要从<strong>你本机</strong>一个已登录的微信
            PC 端页面连接里取。worker 不能代替你登录，也不能操作微信界面，所以它只能等你
            在微信里把这条视频打开并播放一次；页面连上之后，重试就能自动完成下载。
          </p>
          <p className="mt-1">链接始终留在本机，不会发送给任何第三方解析服务。</p>
          <p className="mt-2 font-medium text-[#8a5200]">若提示"本地下载后端未就绪"</p>
          <ol className="list-decimal ml-5">
            <li>在 worker 机器上打开终端，进入 05-src 目录</li>
            <li>
              <code className="px-1 rounded bg-[#ff9500]/10">
                python skills/wechat_channels/wx/install_backend.py --accept-upstream-license
              </code>
            </li>
            <li>按上游要求配置 ~/.local/share/qiaomu-wx-video/local-settings.json 并启动它</li>
            <li>在微信 PC 端打开该视频号播放一次，回到本页点「我已播放，重试」</li>
          </ol>
        </div>
      )}
    </div>
  );
}
