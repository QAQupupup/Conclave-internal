import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

interface ConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  description?: string;
  confirmText?: string; // default: '确认'
  cancelText?: string; // default: '取消'
  destructive?: boolean; // when true, confirm button uses destructive variant
}

export function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title,
  description,
  confirmText = '确认',
  cancelText = '取消',
  destructive = false,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onCancel()}>
      <DialogContent showClose={false} className="max-w-sm">
        <DialogHeader className="pb-4">
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {cancelText}
          </Button>
          <Button variant={destructive ? 'destructive' : 'default'} onClick={onConfirm}>
            {confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
