# FairQueue Dashboard 開発指示書 (Claude Code用)

## プロジェクト概要

**プロジェクト名**: fairque-dashboard  
**技術スタック**: React Admin + FastAPI + TypeScript  
**目的**: FairQueueの包括的Web管理・監視ダッシュボード  
**アーキテクチャ**: フロントエンド(React Admin) + バックエンド(FastAPI) + Redis統合

## ディレクトリ構造

```
/Users/myui/workspace/myui/fairque-dashboard/
├── fairque/                          # Python バックエンド (namespace package)
│   └── dashboard/
│       ├── __init__.py
│       ├── app.py                   # FastAPI メインアプリ
│       ├── cli.py                   # CLI エントリーポイント
│       ├── api/                     # REST API ルーター
│       │   ├── __init__.py
│       │   ├── admin.py             # React Admin用API
│       │   ├── queues.py            # キュー管理API
│       │   ├── tasks.py             # タスク管理API
│       │   ├── workers.py           # ワーカー管理API
│       │   └── websocket.py         # WebSocket API
│       └── core/                    # コア機能
│           ├── __init__.py
│           ├── config.py            # Dashboard設定
│           ├── admin_service.py     # 管理機能サービス
│           └── data_provider.py     # React Admin データプロバイダー
├── frontend/                        # React Admin フロントエンド
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── App.tsx                  # メインアプリケーション
│   │   ├── index.tsx                # エントリーポイント
│   │   ├── providers/               # データプロバイダー
│   │   │   ├── dataProvider.ts      # React Admin データプロバイダー
│   │   │   └── authProvider.ts      # 認証プロバイダー
│   │   ├── resources/               # React Admin リソース
│   │   │   ├── queues/              # キュー管理
│   │   │   │   ├── QueueList.tsx
│   │   │   │   ├── QueueShow.tsx
│   │   │   │   └── QueueEdit.tsx
│   │   │   ├── tasks/               # タスク管理
│   │   │   │   ├── TaskList.tsx
│   │   │   │   ├── TaskShow.tsx
│   │   │   │   └── TaskEdit.tsx
│   │   │   └── workers/             # ワーカー管理
│   │   │       ├── WorkerList.tsx
│   │   │       └── WorkerShow.tsx
│   │   ├── components/              # カスタムコンポーネント
│   │   │   ├── dashboard/           # ダッシュボード特化
│   │   │   │   ├── OverviewDashboard.tsx
│   │   │   │   ├── PriorityQueueChart.tsx
│   │   │   │   └── WorkStealingFlow.tsx
│   │   │   ├── fields/              # カスタムフィールド
│   │   │   │   ├── PriorityField.tsx
│   │   │   │   └── QueueSizeField.tsx
│   │   │   └── inputs/              # カスタム入力
│   │   │       └── PriorityInput.tsx
│   │   ├── hooks/                   # カスタムhooks
│   │   │   ├── useRealTimeMetrics.ts
│   │   │   └── useWebSocket.ts
│   │   └── types/                   # TypeScript型定義
│   │       ├── queue.ts
│   │       ├── task.ts
│   │       └── worker.ts
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── pyproject.toml                   # Python依存関係
├── README.md
└── .gitignore
```

## 開発フェーズ

### Phase 1: Backend基盤 (FastAPI + fairque統合)

#### 1.1 FastAPI アプリケーション設定

**ファイル**: `fairque/dashboard/app.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fairque.dashboard.api import admin, queues, tasks, workers, websocket

def create_app(fairque_config_path: str) -> FastAPI:
    app = FastAPI(
        title="FairQueue Dashboard API",
        description="React Admin compatible API for FairQueue management",
        version="0.1.0"
    )
    
    # CORS設定 (React Dev Server用)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # API routes
    app.include_router(admin.router, prefix="/admin")
    app.include_router(queues.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.include_router(workers.router, prefix="/api")
    app.include_router(websocket.router, prefix="/ws")
    
    # Static files (production)
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
    
    return app
```

#### 1.2 React Admin互換API

**ファイル**: `fairque/dashboard/api/admin.py`

```python
from fastapi import APIRouter, Query, HTTPException, Depends
from typing import List, Optional, Dict, Any
from fairque.dashboard.core.admin_service import AdminService

router = APIRouter(tags=["admin"])

@router.get("/queues")
async def list_queues(
    _start: int = Query(0),
    _end: int = Query(10),
    _sort: str = Query("user_id"),
    _order: str = Query("ASC"),
    user_id: Optional[str] = Query(None),
    service: AdminService = Depends(get_admin_service)
) -> Dict[str, Any]:
    """React Admin compatible queue listing"""
    result = await service.list_queues(_start, _end, _sort, _order, user_id)
    response.headers["X-Total-Count"] = str(result["total"])
    return result["data"]

@router.get("/queues/{id}")
async def get_queue(
    id: str,
    service: AdminService = Depends(get_admin_service)
) -> Dict[str, Any]:
    """Get single queue details"""
    return await service.get_queue(id)

@router.delete("/queues/{id}")
async def delete_queue(
    id: str,
    service: AdminService = Depends(get_admin_service)
) -> Dict[str, Any]:
    """Empty queue (React Admin delete)"""
    return await service.empty_queue(id)

@router.get("/tasks")
async def list_tasks(
    _start: int = Query(0),
    _end: int = Query(10),
    _sort: str = Query("created_at"),
    _order: str = Query("DESC"),
    user_id: Optional[str] = Query(None),
    priority: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    service: AdminService = Depends(get_admin_service)
) -> List[Dict[str, Any]]:
    """React Admin compatible task listing"""
    result = await service.list_tasks(_start, _end, _sort, _order, user_id, priority, status)
    response.headers["X-Total-Count"] = str(result["total"])
    return result["data"]

@router.post("/tasks/{id}/retry")
async def retry_task(
    id: str,
    service: AdminService = Depends(get_admin_service)
) -> Dict[str, Any]:
    """Retry failed task"""
    return await service.retry_task(id)
```

#### 1.3 Admin Service (fairque統合)

**ファイル**: `fairque/dashboard/core/admin_service.py`

```python
from fairque.core.config import FairQueueConfig
from fairque.queue.queue import TaskQueue
import redis
import json
from typing import Dict, List, Any, Optional

class AdminService:
    def __init__(self, fairque_config_path: str):
        self.config = FairQueueConfig.from_yaml(fairque_config_path)
        self.redis_client = self.config.create_redis_client()
    
    async def list_queues(self, start: int, end: int, sort: str, order: str, user_filter: Optional[str] = None) -> Dict[str, Any]:
        """Get paginated and filtered queue list"""
        with TaskQueue(self.config) as queue:
            # Get all queue metrics
            all_queues = queue.get_metrics("queue", "all")
            queues_data = []
            
            for user_id, queue_info in all_queues.get("queues", {}).items():
                if user_filter and user_filter not in user_id:
                    continue
                    
                queues_data.append({
                    "id": user_id,
                    "user_id": user_id,
                    "critical_size": queue_info["critical_size"],
                    "normal_size": queue_info["normal_size"],
                    "total_size": queue_info["total_size"],
                    "priority_distribution": self._get_priority_distribution(user_id),
                    "last_activity": self._get_last_activity(user_id)
                })
            
            # Sort and paginate
            reverse = order.upper() == "DESC"
            sorted_queues = sorted(queues_data, key=lambda x: x.get(sort, ""), reverse=reverse)
            paginated = sorted_queues[start:end]
            
            return {
                "data": paginated,
                "total": len(sorted_queues)
            }
    
    async def list_tasks(self, start: int, end: int, sort: str, order: str, 
                        user_id: Optional[str] = None, priority: Optional[int] = None, 
                        status: Optional[str] = None) -> Dict[str, Any]:
        """Get paginated task list with filtering"""
        # Implementation for scanning Redis for task data
        # This would involve scanning task:* keys and filtering
        tasks_data = self._scan_tasks(user_id, priority, status)
        
        # Sort and paginate
        reverse = order.upper() == "DESC"
        sorted_tasks = sorted(tasks_data, key=lambda x: x.get(sort, ""), reverse=reverse)
        paginated = sorted_tasks[start:end]
        
        return {
            "data": paginated,
            "total": len(sorted_tasks)
        }
    
    async def empty_queue(self, user_id: str) -> Dict[str, Any]:
        """Empty all tasks from user queue"""
        critical_key = f"queue:user:{user_id}:critical"
        normal_key = f"queue:user:{user_id}:normal"
        
        critical_count = self.redis_client.llen(critical_key)
        normal_count = self.redis_client.zcard(normal_key)
        
        # Empty both queues
        self.redis_client.delete(critical_key)
        self.redis_client.delete(normal_key)
        
        return {
            "id": user_id,
            "critical_removed": critical_count,
            "normal_removed": normal_count,
            "total_removed": critical_count + normal_count
        }
```

### Phase 2: Frontend基盤 (React Admin)

#### 2.1 Frontend初期化

**Command**:
```bash
cd /Users/myui/workspace/myui/fairque-dashboard
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install react-admin ra-data-json-server
npm install @mui/material @mui/icons-material @emotion/react @emotion/styled
npm install recharts socket.io-client
```

#### 2.2 React Admin App設定

**ファイル**: `frontend/src/App.tsx`

```tsx
import { Admin, Resource, CustomRoutes } from 'react-admin';
import { Route } from 'react-router-dom';
import { dataProvider } from './providers/dataProvider';
import { authProvider } from './providers/authProvider';

// Resources
import { QueueList, QueueShow, QueueEdit } from './resources/queues';
import { TaskList, TaskShow, TaskEdit } from './resources/tasks';  
import { WorkerList, WorkerShow } from './resources/workers';

// Custom Components
import { OverviewDashboard } from './components/dashboard/OverviewDashboard';
import { PriorityAnalysis } from './components/dashboard/PriorityAnalysis';
import { WorkStealingMonitor } from './components/dashboard/WorkStealingMonitor';

const App = () => (
  <Admin 
    dataProvider={dataProvider}
    authProvider={authProvider}
    dashboard={OverviewDashboard}
    title="FairQueue Dashboard"
  >
    {/* Standard React Admin Resources */}
    <Resource 
      name="queues" 
      list={QueueList} 
      show={QueueShow} 
      edit={QueueEdit}
      recordRepresentation="user_id"
    />
    <Resource 
      name="tasks" 
      list={TaskList} 
      show={TaskShow} 
      edit={TaskEdit}
      recordRepresentation="task_id"
    />
    <Resource 
      name="workers" 
      list={WorkerList} 
      show={WorkerShow}
      recordRepresentation="worker_id"
    />
    
    {/* Custom FairQueue-specific routes */}
    <CustomRoutes>
      <Route path="/priority-analysis" element={<PriorityAnalysis />} />
      <Route path="/work-stealing" element={<WorkStealingMonitor />} />
    </CustomRoutes>
  </Admin>
);

export default App;
```

#### 2.3 Data Provider (React Admin - FastAPI統合)

**ファイル**: `frontend/src/providers/dataProvider.ts`

```typescript
import { DataProvider } from 'react-admin';
import { stringify } from 'query-string';

const apiUrl = 'http://localhost:8080/admin';

export const dataProvider: DataProvider = {
  getList: (resource, params) => {
    const { page, perPage } = params.pagination;
    const { field, order } = params.sort;
    const query = {
      ...params.filter,
      _sort: field,
      _order: order,
      _start: (page - 1) * perPage,
      _end: page * perPage,
    };
    const url = `${apiUrl}/${resource}?${stringify(query)}`;

    return fetch(url)
      .then(response => {
        if (!response.ok) throw new Error('Network error');
        return response.json().then(data => ({
          data,
          total: parseInt(response.headers.get('X-Total-Count') || '0'),
        }));
      });
  },

  getOne: (resource, params) =>
    fetch(`${apiUrl}/${resource}/${params.id}`)
      .then(response => response.json())
      .then(data => ({ data })),

  getMany: (resource, params) => {
    const query = { id: params.ids };
    const url = `${apiUrl}/${resource}?${stringify(query)}`;
    return fetch(url)
      .then(response => response.json())
      .then(data => ({ data }));
  },

  getManyReference: (resource, params) => {
    const { page, perPage } = params.pagination;
    const { field, order } = params.sort;
    const query = {
      ...params.filter,
      [params.target]: params.id,
      _sort: field,
      _order: order,
      _start: (page - 1) * perPage,
      _end: page * perPage,
    };
    const url = `${apiUrl}/${resource}?${stringify(query)}`;

    return fetch(url)
      .then(response => response.json())
      .then(data => ({
        data,
        total: parseInt(response.headers.get('X-Total-Count') || '0'),
      }));
  },

  update: (resource, params) =>
    fetch(`${apiUrl}/${resource}/${params.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params.data),
    })
      .then(response => response.json())
      .then(data => ({ data })),

  updateMany: (resource, params) => {
    const query = { id: params.ids };
    return fetch(`${apiUrl}/${resource}?${stringify(query)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params.data),
    })
      .then(response => response.json())
      .then(data => ({ data: params.ids }));
  },

  create: (resource, params) =>
    fetch(`${apiUrl}/${resource}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params.data),
    })
      .then(response => response.json())
      .then(data => ({ data })),

  delete: (resource, params) =>
    fetch(`${apiUrl}/${resource}/${params.id}`, {
      method: 'DELETE',
    })
      .then(response => response.json())
      .then(data => ({ data })),

  deleteMany: (resource, params) => {
    const query = { id: params.ids };
    return fetch(`${apiUrl}/${resource}?${stringify(query)}`, {
      method: 'DELETE',
    })
      .then(response => response.json())
      .then(data => ({ data: params.ids }));
  },
};
```

### Phase 3: Core Resources (Queue/Task/Worker管理)

#### 3.1 Queue Management

**ファイル**: `frontend/src/resources/queues/QueueList.tsx`

```tsx
import {
  List,
  Datagrid,
  TextField,
  NumberField,
  FunctionField,
  BulkActionButtons,
  DeleteButton,
  EditButton,
  ShowButton,
  SearchInput,
  SelectInput,
  DateField
} from 'react-admin';
import { PriorityQueueChart } from '../../components/dashboard/PriorityQueueChart';

const QueueFilters = [
  <SearchInput source="q" alwaysOn />,
  <SelectInput source="size_range" choices={[
    { id: 'small', name: '< 100 tasks' },
    { id: 'medium', name: '100-1000 tasks' },
    { id: 'large', name: '> 1000 tasks' },
  ]} />,
];

const QueueBulkActions = () => (
  <BulkActionButtons>
    <DeleteButton label="Empty Selected Queues" />
  </BulkActionButtons>
);

export const QueueList = () => (
  <List 
    filters={QueueFilters}
    bulkActionButtons={<QueueBulkActions />}
    sort={{ field: 'total_size', order: 'DESC' }}
  >
    <Datagrid>
      <TextField source="user_id" label="User ID" />
      <NumberField source="critical_size" label="Critical Tasks" />
      <NumberField source="normal_size" label="Normal Tasks" />
      <NumberField source="total_size" label="Total Tasks" />
      <FunctionField 
        source="priority_distribution"
        label="Priority Distribution"
        render={record => (
          <PriorityQueueChart 
            data={record.priority_distribution} 
            width={200} 
            height={50} 
          />
        )}
      />
      <DateField source="last_activity" label="Last Activity" />
      <ShowButton />
      <EditButton />
      <DeleteButton label="Empty" />
    </Datagrid>
  </List>
);
```

#### 3.2 Task Management

**ファイル**: `frontend/src/resources/tasks/TaskList.tsx`

```tsx
import {
  List,
  Datagrid,
  TextField,
  NumberField,
  SelectField,
  DateField,
  SearchInput,
  SelectInput,
  BooleanField,
  FunctionField,
  Button,
  useRecordContext,
  useRefresh,
  useNotify
} from 'react-admin';
import { Chip } from '@mui/material';
import { Replay } from '@mui/icons-material';

const priorityChoices = [
  { id: 1, name: 'Priority 1' },
  { id: 2, name: 'Priority 2' },
  { id: 3, name: 'Priority 3' },
  { id: 4, name: 'Priority 4' },
  { id: 5, name: 'Priority 5' },
  { id: 6, name: 'Critical' },
];

const statusChoices = [
  { id: 'pending', name: 'Pending' },
  { id: 'running', name: 'Running' },
  { id: 'completed', name: 'Completed' },
  { id: 'failed', name: 'Failed' },
  { id: 'retrying', name: 'Retrying' },
];

const TaskFilters = [
  <SearchInput source="q" alwaysOn />,
  <SelectInput source="user_id" choices={[]} />, // Dynamic from API
  <SelectInput source="priority" choices={priorityChoices} />,
  <SelectInput source="status" choices={statusChoices} />,
];

const RetryButton = () => {
  const record = useRecordContext();
  const refresh = useRefresh();
  const notify = useNotify();

  const handleRetry = async () => {
    try {
      await fetch(`/admin/tasks/${record.id}/retry`, { method: 'POST' });
      refresh();
      notify('Task retry initiated', { type: 'success' });
    } catch (error) {
      notify('Error retrying task', { type: 'error' });
    }
  };

  return (
    <Button
      onClick={handleRetry}
      disabled={record.status !== 'failed'}
      label="Retry"
      variant="outlined"
      size="small"
    >
      <Replay />
    </Button>
  );
};

const PriorityChip = ({ priority }: { priority: number }) => {
  const color = priority === 6 ? 'error' : priority >= 4 ? 'warning' : 'default';
  const label = priority === 6 ? 'Critical' : `P${priority}`;
  
  return <Chip label={label} color={color} size="small" />;
};

export const TaskList = () => (
  <List 
    filters={TaskFilters}
    sort={{ field: 'created_at', order: 'DESC' }}
  >
    <Datagrid>
      <TextField source="task_id" label="Task ID" />
      <TextField source="user_id" label="User" />
      <FunctionField 
        source="priority"
        label="Priority"
        render={record => <PriorityChip priority={record.priority} />}
      />
      <SelectField source="status" choices={statusChoices} />
      <DateField source="created_at" label="Created" />
      <DateField source="execute_after" label="Execute After" />
      <NumberField source="retry_count" label="Retries" />
      <BooleanField source="is_function" label="Function Task" />
      <RetryButton />
    </Datagrid>
  </List>
);
```

### Phase 4: Custom Dashboard Components

#### 4.1 Overview Dashboard

**ファイル**: `frontend/src/components/dashboard/OverviewDashboard.tsx`

```tsx
import { Card, CardContent, CardHeader } from 'react-admin';
import { Grid, Typography, Box } from '@mui/material';
import { useGetList } from 'react-admin';
import { MetricsCards } from './MetricsCards';
import { QueueOverviewChart } from './QueueOverviewChart';
import { WorkerStatusCard } from './WorkerStatusCard';
import { RecentActivity } from './RecentActivity';

export const OverviewDashboard = () => {
  const { data: queues, total: queueCount } = useGetList('queues');
  const { data: tasks, total: taskCount } = useGetList('tasks');
  const { data: workers } = useGetList('workers');

  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="h4" gutterBottom>
        FairQueue Dashboard
      </Typography>
      
      <Grid container spacing={3}>
        {/* Metrics Overview */}
        <Grid item xs={12}>
          <MetricsCards 
            queueCount={queueCount}
            taskCount={taskCount}
            workerCount={workers?.length || 0}
          />
        </Grid>
        
        {/* Queue Overview Chart */}
        <Grid item xs={12} md={8}>
          <Card>
            <CardHeader title="Queue Overview" />
            <CardContent>
              <QueueOverviewChart queues={queues || []} />
            </CardContent>
          </Card>
        </Grid>
        
        {/* Worker Status */}
        <Grid item xs={12} md={4}>
          <WorkerStatusCard workers={workers || []} />
        </Grid>
        
        {/* Recent Activity */}
        <Grid item xs={12}>
          <RecentActivity />
        </Grid>
      </Grid>
    </Box>
  );
};
```

#### 4.2 Priority Queue可視化

**ファイル**: `frontend/src/components/dashboard/PriorityQueueChart.tsx`

```tsx
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

interface PriorityData {
  priority: number;
  count: number;
}

interface Props {
  data: Record<string, number>;
  width?: number;
  height?: number;
}

const PRIORITY_COLORS = {
  1: '#4CAF50', // Green
  2: '#8BC34A', // Light Green  
  3: '#FFC107', // Amber
  4: '#FF9800', // Orange
  5: '#FF5722', // Deep Orange
  6: '#F44336', // Red (Critical)
};

export const PriorityQueueChart = ({ data, width = 400, height = 300 }: Props) => {
  const chartData: PriorityData[] = Object.entries(data).map(([priority, count]) => ({
    priority: parseInt(priority),
    count,
    name: priority === '6' ? 'Critical' : `P${priority}`
  }));

  return (
    <ResponsiveContainer width={width} height={height}>
      <BarChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" />
        <YAxis />
        <Tooltip 
          formatter={(value, name) => [value, 'Tasks']}
          labelFormatter={(label) => `Priority: ${label}`}
        />
        <Bar dataKey="count">
          {chartData.map((entry) => (
            <Cell 
              key={`cell-${entry.priority}`} 
              fill={PRIORITY_COLORS[entry.priority]} 
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
};
```

### Phase 5: Real-time機能

#### 5.1 WebSocket Hook

**ファイル**: `frontend/src/hooks/useRealTimeMetrics.ts`

```typescript
import { useEffect, useState, useRef } from 'react';
import { io, Socket } from 'socket.io-client';

interface MetricsData {
  basic: {
    total_tasks: number;
    active_workers: number;
    dlq_size: number;
    push_rate: number;
    pop_rate: number;
  };
  queues: Record<string, any>;
  workers: any[];
  timestamp: number;
}

export const useRealTimeMetrics = () => {
  const [data, setData] = useState<MetricsData | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    // WebSocket connection
    socketRef.current = io('ws://localhost:8080');
    
    socketRef.current.on('connect', () => {
      setIsConnected(true);
    });
    
    socketRef.current.on('disconnect', () => {
      setIsConnected(false);
    });
    
    socketRef.current.on('metrics', (newData: MetricsData) => {
      setData(newData);
    });

    return () => {
      if (socketRef.current) {
        socketRef.current.disconnect();
      }
    };
  }, []);

  return { data, isConnected };
};
```

## 開発コマンド

### Backend開発
```bash
# 開発環境セットアップ
cd /Users/myui/workspace/myui/fairque-dashboard
uv sync

# 開発サーバー起動
fairque-dashboard -c /path/to/fairque_config.yaml --dev
```

### Frontend開発
```bash
# 開発環境セットアップ  
cd /Users/myui/workspace/myui/fairque-dashboard/frontend
npm install

# 開発サーバー起動
npm run dev
```

### 統合テスト
```bash
# Backend + Frontend同時起動
# Terminal 1
fairque-dashboard -c config.yaml --dev

# Terminal 2  
cd frontend && npm run dev
```

## 重要な実装ポイント

### 1. React Admin データプロバイダー
- **X-Total-Count** ヘッダーが必須
- **_start**, **_end** パラメータでページネーション
- **_sort**, **_order** パラメータでソート

### 2. FairQueue統合
- 既存の **get_metrics()** APIを最大活用
- **fairque.core.config** 設定システムの再利用
- **TaskQueue** クラスによる統一アクセス

### 3. エラーハンドリング
```python
# API レスポンス形式統一
@router.get("/queues")
async def list_queues(...):
    try:
        result = await service.list_queues(...)
        response.headers["X-Total-Count"] = str(result["total"])
        return result["data"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 4. TypeScript型定義
```typescript
// frontend/src/types/queue.ts
export interface Queue {
  id: string;
  user_id: string;
  critical_size: number;
  normal_size: number;
  total_size: number;
  priority_distribution: Record<1|2|3|4|5|6, number>;
  last_activity: string;
}

// frontend/src/types/task.ts
export interface Task {
  id: string;
  task_id: string;
  user_id: string;
  priority: 1|2|3|4|5|6;
  status: 'pending'|'running'|'completed'|'failed'|'retrying';
  created_at: string;
  execute_after: string;
  retry_count: number;
  is_function: boolean;
  payload: any;
}

// frontend/src/types/worker.ts
export interface Worker {
  id: string;
  worker_id: string;
  status: 'active'|'idle'|'stopping';
  assigned_users: string[];
  steal_targets: string[];
  active_tasks: number;
  completed_tasks: number;
  last_heartbeat: string;
}
```

## タスク分解と優先度

### High Priority (Week 1-2)
1. **Backend基盤構築**
   - [ ] FastAPI app設定 (`fairque/dashboard/app.py`)
   - [ ] Admin Service実装 (`fairque/dashboard/core/admin_service.py`)
   - [ ] React Admin互換API (`fairque/dashboard/api/admin.py`)
   - [ ] CLI設定 (`fairque/dashboard/cli.py`)

2. **Frontend基盤構築**
   - [ ] React Admin初期化 (`frontend/src/App.tsx`)
   - [ ] Data Provider実装 (`frontend/src/providers/dataProvider.ts`)
   - [ ] 基本認証設定 (`frontend/src/providers/authProvider.ts`)

### Medium Priority (Week 3-4)
3. **Core Resources実装**
   - [ ] Queue管理 (`frontend/src/resources/queues/`)
   - [ ] Task管理 (`frontend/src/resources/tasks/`)
   - [ ] Worker管理 (`frontend/src/resources/workers/`)

4. **カスタムコンポーネント**
   - [ ] Overview Dashboard (`frontend/src/components/dashboard/OverviewDashboard.tsx`)
   - [ ] Priority可視化 (`frontend/src/components/dashboard/PriorityQueueChart.tsx`)
   - [ ] Metrics Cards (`frontend/src/components/dashboard/MetricsCards.tsx`)

### Low Priority (Week 5+)
5. **高度な機能**
   - [ ] Real-time WebSocket (`frontend/src/hooks/useRealTimeMetrics.ts`)
   - [ ] Work Stealing可視化 (`frontend/src/components/dashboard/WorkStealingFlow.tsx`)
   - [ ] 高度なフィルタリング・検索

6. **Production準備**
   - [ ] Docker化 (`docker/`)
   - [ ] テスト実装 (`tests/`)
   - [ ] Documentation更新

## 開発ワークフロー

### 1. Backend First Approach
```bash
# Step 1: Backend基盤実装
cd /Users/myui/workspace/myui/fairque-dashboard
touch fairque/dashboard/{__init__.py,app.py,cli.py}
touch fairque/dashboard/core/{__init__.py,admin_service.py}
touch fairque/dashboard/api/{__init__.py,admin.py}

# Step 2: Basic API動作確認
uvicorn fairque.dashboard.app:app --reload --port 8080

# Step 3: API テスト
curl "http://localhost:8080/admin/queues"
```

### 2. Frontend Integration
```bash
# Step 1: React Admin初期化
cd frontend
npm create vite@latest . -- --template react-ts
npm install react-admin ra-data-json-server

# Step 2: Basic接続確認
npm run dev

# Step 3: Data Provider テスト
# http://localhost:5173でReact Admin動作確認
```

### 3. Iterative Development
- **Backend API実装** → **Frontend Resource実装** の繰り返し
- 各Resourceごとに**List** → **Show** → **Edit**の順で実装
- **Real-time機能**は最後に統合

## デバッグ・トラブルシューティング

### 1. CORS問題
```python
# fairque/dashboard/app.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 2. React Admin Data Provider
```typescript
// X-Total-Count ヘッダー確認
console.log('Total Count:', response.headers.get('X-Total-Count'));

// API レスポンス形式確認
console.log('Data format:', data);
```

### 3. FairQueue統合
```python
# fairque接続テスト
from fairque.core.config import FairQueueConfig
from fairque.queue.queue import TaskQueue

config = FairQueueConfig.from_yaml("path/to/config.yaml")
with TaskQueue(config) as queue:
    metrics = queue.get_metrics("basic")
    print(metrics)
```

## Configuration Examples

### fairque_config.yaml
```yaml
redis:
  host: "localhost"
  port: 6379
  db: 0

workers:
  - id: "worker1"
    assigned_users: ["user_0", "user_1", "user_2"]
    steal_targets: ["user_3", "user_4"]
    max_concurrent_tasks: 10
    poll_interval_seconds: 1.0

queue:
  stats_prefix: "fq"
  enable_pipeline_optimization: true

# Dashboard specific (optional)
dashboard:
  host: "0.0.0.0"
  port: 8080
  enable_cors: true
  update_interval: 1.0
```

### package.json (frontend)
```json
{
  "name": "fairque-dashboard-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-admin": "^4.16.0",
    "ra-data-json-server": "^4.16.0",
    "@mui/material": "^5.14.0",
    "@mui/icons-material": "^5.14.0",
    "@emotion/react": "^11.11.0",
    "@emotion/styled": "^11.11.0",
    "recharts": "^2.8.0",
    "socket.io-client": "^4.7.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@typescript-eslint/eslint-plugin": "^6.0.0",
    "@typescript-eslint/parser": "^6.0.0",
    "@vitejs/plugin-react": "^4.0.0",
    "eslint": "^8.45.0",
    "eslint-plugin-react-hooks": "^4.6.0",
    "eslint-plugin-react-refresh": "^0.4.3",
    "typescript": "^5.0.2",
    "vite": "^4.4.5"
  }
}
```

## Success Criteria

### Phase 1 完了条件
- [ ] FastAPI serverが正常起動
- [ ] `/admin/queues` APIがfairqueデータを返却
- [ ] React Admin基本画面が表示
- [ ] Queue一覧が正常表示

### Phase 2 完了条件
- [ ] Queue/Task/Worker全てのListが動作
- [ ] CRUD操作(最低限Read)が全て動作
- [ ] フィルタリング・ソートが動作

### Phase 3 完了条件
- [ ] Priority可視化が動作
- [ ] Real-time更新が動作
- [ ] カスタムDashboardが動作

### Final完了条件
- [ ] rqmonitor相当の機能が全て動作
- [ ] fairque特有機能が全て動作
- [ ] Production ready (Docker, tests)

## Notes

- **fairque統合**が最重要 - 既存API最大活用
- **React Admin**の標準に従い、カスタマイズは最小限
- **段階的実装** - 動作するものから順次拡張
- **Real-time機能**は最後に実装
- **TypeScript**で型安全性確保
- **エラーハンドリング**を各段階で実装