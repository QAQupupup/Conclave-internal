import * as React from 'react';
import { api } from '@/lib/api';
import { SpinnerIcon } from '@/components/ui/svg-icons';

/**
 * 带鉴权拉取的操作回放截图组件。
 * 后端把浏览器操作截图落盘后，events 只存 screenshot_ref（相对 URL 路径），
 * 前端经 api.imageBlobUrl（携带 Bearer 头）拉取为 object URL 再渲染。
 */
export function RecordingImage({
  src,
  className,
  alt = '操作截图',
}: {
  src: string;
  className?: string;
  alt?: string;
}) {
  const [url, setUrl] = React.useState<string | null>(null);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setUrl(null);
    setError(false);
    api
      .imageBlobUrl(src)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        objectUrl = u;
        setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);

  if (error) {
    return (
      <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-border-default bg-bg-tertiary/30 text-[11px] text-text-tertiary">
        截图加载失败
      </div>
    );
  }
  if (!url) {
    return (
      <div className="flex h-40 items-center justify-center gap-2 rounded-md border border-border-default bg-bg-tertiary/30 text-[11px] text-text-tertiary">
        <SpinnerIcon size={14} className="animate-spin" />
        加载截图中...
      </div>
    );
  }
  return <img src={url} alt={alt} className={className} />;
}