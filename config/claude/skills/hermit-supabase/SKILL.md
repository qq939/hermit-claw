# 十三、Supabase 数据库连接

## 安装方法

1. Install packages:
```
npm install @supabase/supabase-js @supabase/ssr
```

2. Install Agent Skills (Optional):
```
npx skills add supabase/agent-skills
```

## 数据库连接信息

- 连接池地址：postgresql://postgres.uacwkmdyekxyqtopdele:Black_supabase00@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres
- Anon Key：eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVhY3drbWR5ZWt4eXF0b3BkZWxlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzczOTgwNTMsImV4cCI6MjA5Mjk3NDA1M30.bm-LMuDArYuWmoFX8hVV-r3tYs3WgacvqsRcQtwhDe8
- Publishable Key：sb_publishable_ixOQZXbObcNcP-PfiIrILg_PQtGKskp

## 环境变量 (.env.local)
```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_ixOQZXbObcNcP-PfiIrILg_PQtGKskp
```

## 客户端示例 (Next.js)

```typescript
import { createClient } from '@/utils/supabase/server'
import { cookies } from 'next/headers'

export default async function Page() {
  const cookieStore = await cookies()
  const supabase = createClient(cookieStore)
  const { data: todos } = await supabase.from('todos').select()
  return (
    <ul>
      {todos?.map((todo) => (
        <li key={todo.id}>{todo.name}</li>
      ))}
    </ul>
  )
}
```
