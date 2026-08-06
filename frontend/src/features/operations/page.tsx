import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { extractArray } from '@/lib/extract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useToast } from '@/hooks/use-toast';
import { isDemoMode } from '@/lib/mock-data';
import {
  ServerIcon,
  DatabaseIcon,
  CacheIcon,
  ContainerIcon,
  GitIcon,
  CheckCircleIcon,
  XCircleIcon,
  PlayIcon,
  PauseIcon,
  StopIcon,
  RestartIcon,
  PlusIcon,
  CopyIcon,
  RefreshCwIcon,
  ActivityIcon,
  SettingsIcon,
  ChevronIcon,
  MoreHorizontalIcon,
  TrashIcon,
  EditIcon,
} from '@/components/ui/svg-icons';

// ====== Types ======
interface ComponentStatus {
  status: 'healthy' | 'unhealthy' | 'degraded';
  type: string;
  error?: string;
  sandbox_mode?: string;
  active_containers?: number;
}

interface DockerHost {
  id: number;
  name: string;
  connection_type: string;
  status: string;
  region: string;
  tags: string[];
  running_containers: number;
  total_containers: number;
  cpu_cores?: number;
  memory_total?: string;
  memory_used?: string;
  last_health_check?: string;
  error?: string;
}

interface SystemOverview {
  hosts: DockerHost[];
  components: Record<string, ComponentStatus>;
  timestamp: string;
}

interface CommandItem {
  label: string;
  cmd: string;
  description: string;
}

interface CommandCategory {
  category: string;
  commands: CommandItem[];
}

// ====== Mock Data ======
const MOCK_OVERVIEW: SystemOverview = {
  hosts: [
    {
      id: 1,
      name: '本地 Docker (WSL2)',
      connection_type: 'local',
      status: 'healthy',
      region: 'local',
      tags: ['开发环境', '本地'],
      running_containers: 7,
      total_containers: 12,
      cpu_cores: 8,
      memory_total: '16 GB',
      memory_used: '6.2 GB',
      last_health_check: new Date(Date.now() - 3600000).toISOString(),
    },
    {
      id: 2,
      name: '开发服务器',
      connection_type: 'ssh_key',
      status: 'healthy',
      region: 'cn-beijing',
      tags: ['开发环境', '远程'],
      running_containers: 12,
      total_containers: 18,
      cpu_cores: 16,
      memory_total: '32 GB',
      memory_used: '15.8 GB',
      last_health_check: new Date(Date.now() - 1800000).toISOString(),
    },
  ],
  components: {
    postgres: { status: 'healthy', type: 'database' },
    redis: { status: 'healthy', type: 'cache' },
    qdrant: { status: 'healthy', type: 'vector_db' },
    docker: { status: 'healthy', type: 'runtime', sandbox_mode: 'auto', active_containers: 2 },
    backend: { status: 'healthy', type: 'application' },
    frontend: { status: 'healthy', type: 'application' },
    gitea: { status: 'healthy', type: 'git' },
  },
  timestamp: new Date().toISOString(),
};

const MOCK_COMMANDS: CommandCategory[] = [
  {
    category: '启动/停止',
    commands: [
      { label: '启动所有服务', cmd: 'docker compose up -d', description: '后台启动所有 compose 服务' },
      { label: '停止所有服务', cmd: 'docker compose down', description: '停止并移除所有容器（保留数据卷）' },
      { label: '重启后端', cmd: 'docker compose restart backend', description: '仅重启后端容器' },
      { label: '重新构建并启动', cmd: 'docker compose up -d --build', description: '重新构建镜像后启动' },
    ],
  },
  {
    category: '日志查看',
    commands: [
      { label: '查看后端日志', cmd: 'docker compose logs -f backend', description: '实时跟踪后端日志' },
      { label: '查看前端日志', cmd: 'docker compose logs -f frontend', description: '实时跟踪前端日志' },
      { label: '查看所有日志', cmd: 'docker compose logs -f', description: '实时跟踪所有服务日志' },
      { label: '最近 100 行', cmd: 'docker compose logs --tail=100 backend', description: '查看后端最近 100 行日志' },
    ],
  },
  {
    category: '健康检查',
    commands: [
      { label: '服务状态', cmd: 'docker compose ps', description: '查看所有服务运行状态' },
      { label: '健康详情', cmd: 'curl -s http://localhost:8000/health | python -m json.tool', description: '查看详细健康检查 JSON' },
      { label: '系统指标', cmd: 'curl -s http://localhost:8000/metrics | python -m json.tool', description: '查看系统运行指标' },
    ],
  },
  {
    category: '数据管理',
    commands: [
      { label: '查看数据卷', cmd: 'docker volume ls | grep conclave', description: '列出所有 Conclave 数据卷' },
      { label: '备份数据库', cmd: 'docker compose exec postgres pg_dump -U conclave conclave > backup.sql', description: '导出 PostgreSQL 数据库' },
      { label: '恢复数据库', cmd: 'cat backup.sql | docker compose exec -T postgres psql -U conclave conclave', description: '从 SQL 文件恢复数据库' },
      { label: '清理数据（危险）', cmd: 'docker compose down -v', description: '停止并删除所有数据卷（不可恢复！）' },
    ],
  },
  {
    category: '调试',
    commands: [
      { label: '进入后端容器', cmd: 'docker compose exec backend bash', description: '在后端容器内打开 Shell' },
      { label: '进入数据库', cmd: 'docker compose exec postgres psql -U conclave', description: '打开 psql 交互式终端' },
      { label: '查看容器资源', cmd: 'docker stats --no-stream', description: '查看所有容器的 CPU/内存使用' },
      { label: '检查网络', cmd: 'docker network inspect conclave-dev_conclave-internal', description: '查看内部网络详情' },
    ],
  },
];

// ====== Component Icons ======
const COMPONENT_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  database: DatabaseIcon,
  cache: CacheIcon,
  vector_db: DatabaseIcon,
  runtime: ContainerIcon,
  application: ServerIcon,
  git: GitIcon,
};

const STATUS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  healthy: { bg: 'bg-green-50', text: 'text-green-700', border: 'border-green-200' },
  unhealthy: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200' },
  degraded: { bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200' },
};

// ====== SVG Topology Component ======
function SystemTopology({
  overview,
  onComponentAction,
}: {
  overview: SystemOverview;
  onComponentAction: (componentId: string, action: 'restart' | 'check') => void;
}) {
  const [selectedNode, setSelectedNode] = React.useState<string | null>(null);

  const nodes = [
    { id: 'postgres', label: 'PostgreSQL', x: 100, y: 80, ...overview.components.postgres },
    { id: 'redis', label: 'Redis', x: 250, y: 80, ...overview.components.redis },
    { id: 'qdrant', label: 'Qdrant', x: 400, y: 80, ...overview.components.qdrant },
    { id: 'backend', label: 'Backend', x: 175, y: 200, ...overview.components.backend },
    { id: 'frontend', label: 'Frontend', x: 325, y: 200, ...overview.components.frontend },
    { id: 'docker', label: 'Docker', x: 100, y: 320, ...overview.components.docker },
    { id: 'gitea', label: 'Gitea', x: 400, y: 320, ...overview.components.gitea },
  ];

  const connections = [
    { from: 'postgres', to: 'backend' },
    { from: 'redis', to: 'backend' },
    { from: 'qdrant', to: 'backend' },
    { from: 'backend', to: 'frontend' },
    { from: 'backend', to: 'docker' },
    { from: 'backend', to: 'gitea' },
  ];

  const getNodeById = (id: string) => nodes.find((n) => n.id === id);

  return (
    <div className="relative">
      <svg width="500" height="400" className="w-full h-auto">
        {/* Connections */}
        {connections.map((conn, idx) => {
          const from = getNodeById(conn.from);
          const to = getNodeById(conn.to);
          if (!from || !to) return null;
          return (
            <line
              key={idx}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke="#d1d5db"
              strokeWidth="2"
              strokeDasharray="4"
            />
          );
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const Icon = COMPONENT_ICONS[node.type] || ServerIcon;
          const colors = STATUS_COLORS[node.status] || STATUS_COLORS.healthy;
          const isSelected = selectedNode === node.id;

          return (
            <g
              key={node.id}
              onClick={() => setSelectedNode(isSelected ? null : node.id)}
              className="cursor-pointer"
            >
              {/* Node circle */}
              <circle
                cx={node.x}
                cy={node.y}
                r="35"
                fill={colors.bg}
                stroke={isSelected ? '#335c8e' : colors.border}
                strokeWidth={isSelected ? 3 : 2}
                className="transition-all"
              />
              {/* Icon */}
              <foreignObject x={node.x - 12} y={node.y - 12} width="24" height="24">
                <div className={`flex items-center justify-center ${colors.text}`}>
                  <Icon size={20} />
                </div>
              </foreignObject>
              {/* Label */}
              <text
                x={node.x}
                y={node.y + 50}
                textAnchor="middle"
                className="text-xs fill-text-secondary font-medium"
              >
                {node.label}
              </text>
              {/* Status indicator */}
              <circle
                cx={node.x + 25}
                cy={node.y - 25}
                r="6"
                fill={node.status === 'healthy' ? '#10b981' : node.status === 'degraded' ? '#f59e0b' : '#ef4444'}
                stroke="white"
                strokeWidth="2"
              />
            </g>
          );
        })}
      </svg>

      {/* Selected node details */}
      {selectedNode && (
        <div className="absolute top-4 right-4 w-64 bg-bg-primary border border-border-default rounded-lg shadow-sm p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-text-primary">
              {nodes.find((n) => n.id === selectedNode)?.label}
            </h3>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSelectedNode(null)}
              className="h-6 w-6 p-0"
            >
              <XCircleIcon size={16} />
            </Button>
          </div>
          <div className="space-y-2 text-xs">
            <div className="flex justify-between">
              <span className="text-text-tertiary">状态:</span>
              <Badge className={STATUS_COLORS[overview.components[selectedNode]?.status || 'healthy'].bg}>
                {overview.components[selectedNode]?.status || 'unknown'}
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-text-tertiary">类型:</span>
              <span className="text-text-primary">{overview.components[selectedNode]?.type}</span>
            </div>
            {overview.components[selectedNode]?.error && (
              <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-red-700 text-xs max-h-32 overflow-auto">
                <div className="font-medium mb-1">组件错误：</div>
                {overview.components[selectedNode].error?.slice(0, 500) || '未知错误'}
              </div>
            )}
            <div className="flex gap-2 mt-3">
              <Button
                size="sm"
                variant="outline"
                className="flex-1"
                onClick={() => onComponentAction(selectedNode, 'restart')}
              >
                <RestartIcon size={12} className="mr-1" />
                重启
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="flex-1"
                onClick={() => onComponentAction(selectedNode, 'check')}
              >
                <RefreshCwIcon size={12} className="mr-1" />
                检查
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ====== Command Card Component ======
function CommandCard({ command }: { command: CommandItem }) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(command.cmd);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="group relative bg-bg-secondary hover:bg-bg-tertiary border border-border-soft rounded-lg p-3 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="font-medium text-text-primary text-sm mb-1">{command.label}</div>
          <div className="text-xs text-text-tertiary mb-2">{command.description}</div>
          <code className="block text-xs bg-bg-primary border border-border-default rounded px-2 py-1.5 font-mono text-text-secondary overflow-x-auto">
            {command.cmd}
          </code>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleCopy}
          className="h-8 w-8 p-0 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
        >
          {copied ? <CheckCircleIcon size={14} className="text-green-600" /> : <CopyIcon size={14} />}
        </Button>
      </div>
    </div>
  );
}

// ====== Container Action Component ======
function ContainerActions({ hostId, containerId }: { hostId: number; containerId: string }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const actionMutation = useMutation({
    mutationFn: async ({ action }: { action: string }): Promise<{ ok: boolean; action?: string }> => {
      if (isDemoMode()) {
        await new Promise((r) => setTimeout(r, 500));
        return { ok: true, action };
      }
      return api.post<{ ok: boolean; action?: string }>(`/docker-hosts/${hostId}/containers/${containerId}/action`, { action });
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['operations', 'overview'] });
      toast({ title: '操作成功', description: `容器操作 ${data.action || ''} 已执行` });
    },
    onError: (err: Error) => {
      toast({ title: '操作失败', description: err.message, variant: 'destructive' });
    },
  });

  return (
    <div className="flex gap-1">
      <Button
        size="sm"
        variant="ghost"
        onClick={() => actionMutation.mutate({ action: 'start' })}
        disabled={actionMutation.isPending}
        title="启动"
      >
        <PlayIcon size={14} className="text-green-600" />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => actionMutation.mutate({ action: 'pause' })}
        disabled={actionMutation.isPending}
        title="暂停"
      >
        <PauseIcon size={14} className="text-yellow-600" />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => actionMutation.mutate({ action: 'restart' })}
        disabled={actionMutation.isPending}
        title="重启"
      >
        <RestartIcon size={14} className="text-blue-600" />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => actionMutation.mutate({ action: 'stop' })}
        disabled={actionMutation.isPending}
        title="停止"
      >
        <StopIcon size={14} className="text-red-600" />
      </Button>
    </div>
  );
}

interface ContainerInfo {
  id: string;
  name: string;
  status: string;
  image: string;
}

// ====== Docker Host Card Component ======
function DockerHostCard({
  host,
  expanded,
  onToggleExpand,
  onEdit,
  onDelete,
}: {
  host: DockerHost;
  expanded: boolean;
  onToggleExpand: () => void;
  onEdit: (host: DockerHost) => void;
  onDelete: (hostId: number) => void;
}) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const healthCheckMutation = useMutation({
    mutationFn: async () => {
      if (isDemoMode()) {
        await new Promise((r) => setTimeout(r, 1000));
        return { ok: true };
      }
      return api.post(`/docker-hosts/${host.id}/health-check`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['operations', 'overview'] });
      toast({ title: '健康检查完成' });
    },
    onError: (err: Error) => {
      toast({ title: '健康检查失败', description: err.message, variant: 'destructive' });
    },
  });

  // Fetch containers when expanded
  const { data: containersData, isLoading: containersLoading } = useQuery({
    queryKey: ['operations', 'containers', host.id],
    queryFn: async () => {
      if (isDemoMode()) {
        await new Promise((r) => setTimeout(r, 400));
        return {
          containers: [
            { id: 'c1', name: 'conclave-backend', status: 'running', image: 'conclave/backend:latest' },
            { id: 'c2', name: 'conclave-frontend', status: 'running', image: 'conclave/frontend:latest' },
            { id: 'c3', name: 'postgres', status: 'running', image: 'postgres:16-alpine' },
            { id: 'c4', name: 'redis', status: 'running', image: 'redis:7-alpine' },
          ] as ContainerInfo[],
        };
      }
      return api.get<{ containers: ContainerInfo[] }>(`/docker-hosts/${host.id}/containers`);
    },
    enabled: expanded,
  });

  const statusColors = STATUS_COLORS[host.status] || STATUS_COLORS.unhealthy;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${statusColors.bg}`}>
              <ServerIcon size={20} className={statusColors.text} />
            </div>
            <div>
              <CardTitle className="text-base">{host.name}</CardTitle>
              <CardDescription className="text-xs">
                {host.connection_type === 'local' ? '本地环境' : `SSH 连接 · ${host.region}`}
              </CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge className={statusColors.bg + ' ' + statusColors.text}>
              {host.status === 'healthy' ? '正常' : host.status === 'degraded' ? '降级' : '异常'}
            </Badge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="ghost" className="h-7 w-7 p-0">
                  <MoreHorizontalIcon size={14} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onEdit(host)}>
                  <EditIcon size={14} className="mr-2" />
                  编辑
                </DropdownMenuItem>
                <DropdownMenuItem destructive onClick={() => onDelete(host.id)}>
                  <TrashIcon size={14} className="mr-2" />
                  删除主机
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="space-y-3">
          {/* Stats */}
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div>
              <div className="text-text-tertiary">容器</div>
              <div className="font-semibold text-text-primary">
                {host.running_containers} / {host.total_containers}
              </div>
            </div>
            {host.cpu_cores && (
              <div>
                <div className="text-text-tertiary">CPU</div>
                <div className="font-semibold text-text-primary">{host.cpu_cores} 核</div>
              </div>
            )}
            {host.memory_total && (
              <div>
                <div className="text-text-tertiary">内存</div>
                <div className="font-semibold text-text-primary">{host.memory_used} / {host.memory_total}</div>
              </div>
            )}
          </div>

          {/* Tags */}
          {Array.isArray(host.tags) && host.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {host.tags.map((tag) => (
                <Badge key={tag} variant="outline" className="text-xs">
                  {tag}
                </Badge>
              ))}
            </div>
          )}

          {/* Last health check */}
          {host.last_health_check && (
            <div className="text-xs text-text-tertiary">
              最后检查: {new Date(host.last_health_check).toLocaleString('zh-CN')}
            </div>
          )}

          {/* Error */}
          {host.error && (
            <div className="p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 max-h-24 overflow-auto">
              <div className="font-medium mb-0.5">主机错误：</div>
              {host.error.slice(0, 300)}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-2 border-t border-border-soft">
            <Button
              size="sm"
              variant="outline"
              onClick={() => healthCheckMutation.mutate()}
              disabled={healthCheckMutation.isPending}
              className="flex-1"
            >
              <RefreshCwIcon size={14} className="mr-1" />
              健康检查
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={onToggleExpand}
            >
              <ChevronIcon
                size={12}
                className="mr-1"
                direction={expanded ? 'up' : 'down'}
              />
              {expanded ? '收起' : '展开容器'}
            </Button>
          </div>

          {/* Container list */}
          {expanded && (
            <div className="border-t border-border-soft pt-3">
              {containersLoading ? (
                <div className="flex items-center justify-center py-4">
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-border-default border-t-brand-500" />
                </div>
              ) : !containersData?.containers || containersData.containers.length === 0 ? (
                <div className="text-xs text-text-tertiary text-center py-3">暂无容器</div>
              ) : (
                <div className="space-y-2">
                  {containersData.containers.map((container) => (
                    <div
                      key={container.id}
                      className="flex items-center justify-between gap-2 rounded-md border border-border-soft bg-bg-secondary/50 px-3 py-2"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <ContainerIcon size={14} className="text-text-tertiary flex-shrink-0" />
                          <span className="text-xs font-medium text-text-primary truncate">
                            {container.name}
                          </span>
                          <Badge
                            variant="outline"
                            className={`text-[10px] ${
                              container.status === 'running'
                                ? 'text-green-700 border-green-200'
                                : 'text-text-tertiary'
                            }`}
                          >
                            {container.status}
                          </Badge>
                        </div>
                        <div className="text-[10px] text-text-tertiary truncate ml-5 mt-0.5">
                          {container.image}
                        </div>
                      </div>
                      <ContainerActions hostId={host.id} containerId={container.id} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ====== Main Page Component ======
export default function OperationsPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState('overview');

  // Container expansion state per host
  const [showContainers, setShowContainers] = React.useState<Record<number, boolean>>({});

  // Add / Edit host dialog state
  const [hostDialogOpen, setHostDialogOpen] = React.useState(false);
  const [editingHost, setEditingHost] = React.useState<DockerHost | null>(null);
  const [hostForm, setHostForm] = React.useState({
    name: '',
    connection_type: 'local' as 'local' | 'ssh_key',
    docker_host: '',
    region: '',
    tags: '',
  });

  // Reset form when dialog opens/closes
  const openAddHostDialog = () => {
    setEditingHost(null);
    setHostForm({ name: '', connection_type: 'local', docker_host: '', region: '', tags: '' });
    setHostDialogOpen(true);
  };

  const openEditHostDialog = (host: DockerHost) => {
    setEditingHost(host);
    setHostForm({
      name: host.name,
      connection_type: host.connection_type as 'local' | 'ssh_key',
      docker_host: '',
      region: host.region || '',
      tags: Array.isArray(host.tags) ? host.tags.join(', ') : '',
    });
    setHostDialogOpen(true);
  };

  // Fetch system overview
  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ['operations', 'overview'],
    queryFn: async () => {
      if (isDemoMode()) {
        await new Promise((r) => setTimeout(r, 300));
        return MOCK_OVERVIEW;
      }
      return api.get<SystemOverview>('/docker-hosts/overview');
    },
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  // Fetch commands reference
  const { data: commands, isLoading: commandsLoading } = useQuery({
    queryKey: ['operations', 'commands'],
    queryFn: async () => {
      if (isDemoMode()) {
        await new Promise((r) => setTimeout(r, 200));
        return MOCK_COMMANDS;
      }
      return api.get<CommandCategory[] | { commands: CommandCategory[] }>(
        '/docker-hosts/commands-reference'
      ).then((res) => extractArray<CommandCategory>(res, ['commands']));
    },
  });

  // Refresh all data
  const handleRefreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['operations'] });
    toast({ title: '正在刷新所有数据...' });
  };

  // Component action handler (from SystemTopology)
  const handleComponentAction = (componentId: string, action: 'restart' | 'check') => {
    if (action === 'check') {
      queryClient.invalidateQueries({ queryKey: ['operations', 'overview'] });
      toast({ title: `正在检查 ${componentId}...` });
    } else if (action === 'restart') {
      if (componentId === 'docker') {
        queryClient.invalidateQueries({ queryKey: ['operations', 'overview'] });
        toast({ title: 'Docker 运行时检查完成' });
      } else {
        toast({
          title: '重启提示',
          description: '请通过「命令参考」中的 Docker Compose 命令重启服务',
        });
      }
    }
  };

  // Add / Edit host mutation
  const saveHostMutation = useMutation({
    mutationFn: async () => {
      const formData = {
        name: hostForm.name,
        connection_type: hostForm.connection_type,
        docker_host: hostForm.docker_host || undefined,
        region: hostForm.region || undefined,
        tags: hostForm.tags
          ? hostForm.tags.split(',').map((t) => t.trim()).filter(Boolean)
          : [],
      };
      if (isDemoMode()) {
        await new Promise((r) => setTimeout(r, 600));
        return { ok: true };
      }
      if (editingHost) {
        return api.put(`/docker-hosts/${editingHost.id}`, formData);
      }
      return api.post('/docker-hosts', formData);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['operations', 'overview'] });
      toast({ title: editingHost ? '主机已更新' : '主机已添加' });
      setHostDialogOpen(false);
    },
    onError: (err: Error) => {
      toast({ title: '操作失败', description: err.message, variant: 'destructive' });
    },
  });

  // Delete host mutation
  const deleteHostMutation = useMutation({
    mutationFn: async (hostId: number) => {
      if (isDemoMode()) {
        await new Promise((r) => setTimeout(r, 400));
        return { ok: true };
      }
      return api.delete(`/docker-hosts/${hostId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['operations', 'overview'] });
      toast({ title: '主机已删除' });
    },
    onError: (err: Error) => {
      toast({ title: '删除失败', description: err.message, variant: 'destructive' });
    },
  });

  const toggleContainer = (hostId: number) => {
    setShowContainers((prev) => ({ ...prev, [hostId]: !prev[hostId] }));
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-border-soft bg-bg-primary p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ActivityIcon size={20} className="text-brand-500" />
            <h2 className="text-lg font-semibold text-text-primary">运维管理</h2>
          </div>
          <Button size="sm" variant="outline" onClick={handleRefreshAll}>
            <RefreshCwIcon size={14} className="mr-1" />
            刷新
          </Button>
        </div>
        <p className="text-xs text-text-tertiary mt-1">
          监控系统组件、管理容器和远程主机
        </p>
      </div>

      {/* Content */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col">
        <div className="flex-shrink-0 border-b border-border-soft bg-bg-primary px-4">
          <TabsList className="h-10 bg-transparent gap-0 p-0">
            <TabsTrigger
              value="overview"
              className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-brand-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-3 gap-1.5"
            >
              <ActivityIcon size={14} />
              系统概览
            </TabsTrigger>
            <TabsTrigger
              value="hosts"
              className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-brand-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-3 gap-1.5"
            >
              <ServerIcon size={14} />
              Docker 主机
              <Badge className="ml-1 bg-bg-tertiary text-text-tertiary text-[10px] px-1 py-0">
                {overview?.hosts?.length ?? 0}
              </Badge>
            </TabsTrigger>
            <TabsTrigger
              value="commands"
              className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-brand-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-3 gap-1.5"
            >
              <SettingsIcon size={14} />
              命令参考
            </TabsTrigger>
          </TabsList>
        </div>

        <ScrollArea className="flex-1">
          {/* Overview Tab */}
          <TabsContent value="overview" className="p-4 m-0">
            {overviewLoading && !overview ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-border-default border-t-brand-500" />
              </div>
            ) : !overview ? (
              <div className="flex items-center justify-center py-12 text-text-tertiary text-xs">
                暂无系统概览数据
              </div>
            ) : (
            <div className="space-y-6">
              {/* System Topology */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">系统拓扑图</CardTitle>
                  <CardDescription>点击组件查看详情并执行操作</CardDescription>
                </CardHeader>
                <CardContent>
                  <SystemTopology overview={overview} onComponentAction={handleComponentAction} />
                </CardContent>
              </Card>

              {/* Component Status Grid */}
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                {overview?.components && typeof overview.components === 'object' && Object.entries(overview.components).map(([key, component]) => {
                  const Icon = COMPONENT_ICONS[component.type] || ServerIcon;
                  const colors = STATUS_COLORS[component.status] || STATUS_COLORS.healthy;

                  return (
                    <Card key={key} className="hover:shadow-md transition-shadow">
                      <CardContent className="p-4">
                        <div className="flex items-center gap-3">
                          <div className={`p-2 rounded-lg ${colors.bg}`}>
                            <Icon size={20} className={colors.text} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-text-primary text-sm capitalize">
                              {key}
                            </div>
                            <Badge className={`${colors.bg} ${colors.text} text-xs mt-1`}>
                              {component.status}
                            </Badge>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </div>
            )}
          </TabsContent>

          {/* Hosts Tab */}
          <TabsContent value="hosts" className="p-4 m-0">
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <h3 className="text-sm font-medium text-text-primary">Docker 主机列表</h3>
                <Dialog open={hostDialogOpen} onOpenChange={setHostDialogOpen}>
                  <DialogTrigger asChild>
                    <Button size="sm" onClick={openAddHostDialog}>
                      <PlusIcon size={14} className="mr-1" />
                      添加主机
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>{editingHost ? '编辑主机' : '添加主机'}</DialogTitle>
                    </DialogHeader>
                    <div className="px-6 py-4 space-y-4">
                      <div className="space-y-1.5">
                        <Label htmlFor="host-name" className="text-xs">名称</Label>
                        <Input
                          id="host-name"
                          placeholder="例如：本地 Docker (WSL2)"
                          value={hostForm.name}
                          onChange={(e) => setHostForm((f) => ({ ...f, name: e.target.value }))}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="host-conn-type" className="text-xs">连接类型</Label>
                        <Select
                          value={hostForm.connection_type}
                          onValueChange={(v: 'local' | 'ssh_key') =>
                            setHostForm((f) => ({ ...f, connection_type: v }))
                          }
                        >
                          <SelectTrigger id="host-conn-type">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="local">本地 (local)</SelectItem>
                            <SelectItem value="ssh_key">SSH 密钥 (ssh_key)</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="host-docker-host" className="text-xs">Docker Host（可选）</Label>
                        <Input
                          id="host-docker-host"
                          placeholder="例如：unix:///var/run/docker.sock"
                          value={hostForm.docker_host}
                          onChange={(e) => setHostForm((f) => ({ ...f, docker_host: e.target.value }))}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="host-region" className="text-xs">区域（可选）</Label>
                        <Input
                          id="host-region"
                          placeholder="例如：cn-beijing"
                          value={hostForm.region}
                          onChange={(e) => setHostForm((f) => ({ ...f, region: e.target.value }))}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="host-tags" className="text-xs">标签（逗号分隔，可选）</Label>
                        <Input
                          id="host-tags"
                          placeholder="例如：开发环境, 本地"
                          value={hostForm.tags}
                          onChange={(e) => setHostForm((f) => ({ ...f, tags: e.target.value }))}
                        />
                      </div>
                    </div>
                    <DialogFooter>
                      <Button
                        variant="outline"
                        onClick={() => setHostDialogOpen(false)}
                      >
                        取消
                      </Button>
                      <Button
                        onClick={() => saveHostMutation.mutate()}
                        disabled={saveHostMutation.isPending || !hostForm.name.trim()}
                      >
                        {saveHostMutation.isPending ? '保存中...' : editingHost ? '保存' : '添加'}
                      </Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </div>

              {overviewLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="h-8 w-8 animate-spin rounded-full border-2 border-border-default border-t-brand-500" />
                </div>
              ) : !overview?.hosts || overview.hosts.length === 0 ? (
                <Card>
                  <CardContent className="py-12 text-center">
                    <ServerIcon size={48} className="mx-auto text-text-tertiary mb-3" />
                    <p className="text-sm text-text-secondary mb-1">暂无 Docker 主机</p>
                    <p className="text-xs text-text-tertiary">点击"添加主机"配置本地或远程 Docker 环境</p>
                  </CardContent>
                </Card>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {overview?.hosts?.map((host) => (
                    <DockerHostCard
                      key={host.id}
                      host={host}
                      expanded={!!showContainers[host.id]}
                      onToggleExpand={() => toggleContainer(host.id)}
                      onEdit={openEditHostDialog}
                      onDelete={(id) => deleteHostMutation.mutate(id)}
                    />
                  ))}
                </div>
              )}
            </div>
          </TabsContent>

          {/* Commands Tab */}
          <TabsContent value="commands" className="p-4 m-0">
            {commandsLoading && !commands ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-border-default border-t-brand-500" />
              </div>
            ) : !commands || commands.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-text-tertiary text-xs">
                暂无命令参考数据
              </div>
            ) : (
            <div className="space-y-6">
              {Array.isArray(commands) && commands.map((category) => (
                <div key={category.category}>
                  <h3 className="text-sm font-medium text-text-primary mb-3">{category.category}</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {Array.isArray(category.commands) && category.commands.map((cmd, idx) => (
                      <CommandCard key={idx} command={cmd} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
            )}
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </div>
  );
}
