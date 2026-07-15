// 登录页面：简洁的居中登录表单
import { useState } from 'react'
import { Form, Input, Button, Card, Typography, message } from 'antd'
import { UserOutlined, LockOutlined, SafetyOutlined } from '@ant-design/icons'
import { useAuth } from '../store/AuthContext.tsx'

const { Title, Text, Paragraph } = Typography

export function LoginPage() {
  const { login } = useAuth()
  const [loading, setLoading] = useState(false)

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      await login(values.username, values.password)
      message.success('登录成功')
    } catch (err: any) {
      message.error(err.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #f5f7fa 0%, #e4e9f2 100%)',
        padding: 24,
      }}
    >
      <Card
        style={{
          width: 400,
          borderRadius: 12,
          boxShadow: '0 8px 32px rgba(0,0,0,0.08)',
        }}
        bodyStyle={{ padding: '36px 32px 28px' }}
      >
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: '50%',
              background: 'var(--success, #2d8a56)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: 16,
              boxShadow: '0 4px 12px rgba(45,138,86,0.25)',
            }}
          >
            <SafetyOutlined style={{ fontSize: 28, color: '#fff' }} />
          </div>
          <Title level={3} style={{ margin: '0 0 4px', fontWeight: 600 }}>
            Conclave
          </Title>
          <Text type="secondary">多智能体协作会议系统</Text>
        </div>

        <Form
          name="login"
          onFinish={onFinish}
          autoComplete="off"
          size="large"
          initialValues={{ username: 'admin' }}
        >
          <Form.Item
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input
              prefix={<UserOutlined style={{ color: '#bfbfbf' }} />}
              placeholder="用户名"
              autoComplete="username"
            />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined style={{ color: '#bfbfbf' }} />}
              placeholder="密码"
              autoComplete="current-password"
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 12 }}>
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              style={{
                height: 42,
                fontWeight: 500,
                background: 'var(--success, #2d8a56)',
                borderColor: 'var(--success, #2d8a56)',
              }}
            >
              登录
            </Button>
          </Form.Item>
        </Form>

        <Paragraph
          type="secondary"
          style={{ fontSize: 12, textAlign: 'center', margin: '12px 0 0', lineHeight: 1.6 }}
        >
          默认管理员账号：admin / admin123
          <br />
          请在生产环境中通过环境变量 <Text code>CONCLAVE_ADMIN_PASSWORD</Text> 修改默认密码
        </Paragraph>
      </Card>
    </div>
  )
}
