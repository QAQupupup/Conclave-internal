import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * FieldError — 字段级校验错误文本
 *
 * 表单校验错误的唯一字段级载体：紧贴字段下方展示，通过 id 与字段的
 * aria-describedby 关联，role="alert" 保证屏幕阅读器即时播报。
 * 禁止用 toast 承载字段校验错误（toast 仅用于操作结果反馈）。
 */
export function FieldError({
  id,
  className,
  children,
}: {
  id?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  if (React.Children.count(children) === 0 || children === '' || children == null) {
    return null;
  }
  return (
    <p id={id} role="alert" className={cn('text-xs leading-4 text-danger', className)}>
      {children}
    </p>
  );
}

/**
 * FormAlert — 表单级错误横幅
 *
 * 承载无法归属到单一字段的错误：服务端拒绝（用户名或密码错误）、
 * 网络/连接异常等。置于表单字段与提交按钮之间。
 */
export function FormAlert({
  className,
  children,
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  if (React.Children.count(children) === 0 || children === '' || children == null) {
    return null;
  }
  return (
    <div role="alert" className={cn('rounded-md bg-danger-bg px-2.5 py-2 text-xs text-danger', className)}>
      {children}
    </div>
  );
}
