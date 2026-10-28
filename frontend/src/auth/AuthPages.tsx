import { Alert, Anchor, Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { useForm } from '@mantine/form';
import { useState, type ReactNode } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { useAuth } from './AuthProvider';

function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Center mih="100dvh" px="md" bg="var(--mantine-color-gray-0)">
      <Paper withBorder shadow="sm" radius="md" p="lg" w="100%" maw={400}>
        <Stack gap="md">
          <div>
            <Text size="sm" c="dimmed" fw={600}>Finance ERP</Text>
            <Title order={2}>{title}</Title>
          </div>
          {children}
        </Stack>
      </Paper>
    </Center>
  );
}

const emailRule = (v: string) => (/^\S+@\S+\.\S+$/.test(v) ? null : 'Enter a valid email');

export function LoginPage() {
  const { session } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const form = useForm({ initialValues: { email: '', password: '' }, validate: { email: emailRule } });

  if (session) return <Navigate to="/" replace />;

  const submit = form.onSubmit(async ({ email, password }) => {
    setBusy(true);
    setError(null);
    const { error: err } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
    setBusy(false);
    // Same message for wrong email or password: do not reveal which accounts exist.
    if (err) setError(err.status === 429 ? 'Too many attempts. Wait a few minutes.' : 'Incorrect email or password.');
  });

  return (
    <AuthCard title="Sign in">
      <form onSubmit={submit} noValidate>
        <Stack>
          {error && <Alert color="red" role="alert">{error}</Alert>}
          <TextInput label="Email" type="email" autoComplete="username" inputMode="email" size="md"
            {...form.getInputProps('email')} />
          <PasswordInput label="Password" autoComplete="current-password" size="md" {...form.getInputProps('password')} />
          <Button type="submit" size="md" loading={busy} fullWidth>Sign in</Button>
          <Anchor component={Link} to="/forgot-password" size="sm" ta="center">Forgot password?</Anchor>
        </Stack>
      </form>
    </AuthCard>
  );
}

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const form = useForm({ initialValues: { email: '' }, validate: { email: emailRule } });

  const submit = form.onSubmit(async ({ email }) => {
    setBusy(true);
    await supabase.auth.resetPasswordForEmail(email.trim(), { redirectTo: `${window.location.origin}/set-password` });
    setBusy(false);
    setSent(true); // always show success: do not reveal whether the email exists
  });

  return (
    <AuthCard title="Reset password">
      {sent ? (
        <Alert color="green">If this email belongs to an account, a reset link has been sent. Check your inbox.</Alert>
      ) : (
        <form onSubmit={submit} noValidate>
          <Stack>
            <TextInput label="Email" type="email" inputMode="email" size="md" {...form.getInputProps('email')} />
            <Button type="submit" size="md" loading={busy} fullWidth>Send reset link</Button>
          </Stack>
        </form>
      )}
      <Anchor component={Link} to="/login" size="sm" ta="center">Back to sign in</Anchor>
    </AuthCard>
  );
}

export function SetPasswordPage() {
  const navigate = useNavigate();
  const { session, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const form = useForm({
    initialValues: { password: '', confirm: '' },
    validate: {
      password: (v) => (v.length >= 10 ? null : 'Use at least 10 characters'),
      confirm: (v, all) => (v === all.password ? null : 'Passwords do not match'),
    },
  });

  if (!loading && !session) {
    return (
      <AuthCard title="Link expired">
        <Text>This link is invalid or has expired. Ask for a new one.</Text>
        <Anchor component={Link} to="/forgot-password">Request a new link</Anchor>
      </AuthCard>
    );
  }

  const submit = form.onSubmit(async ({ password }) => {
    setBusy(true);
    const { error: err } = await supabase.auth.updateUser({ password });
    setBusy(false);
    if (err) setError(err.message);
    else navigate('/', { replace: true });
  });

  return (
    <AuthCard title="Choose your password">
      <form onSubmit={submit} noValidate>
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <PasswordInput label="New password" autoComplete="new-password" size="md" {...form.getInputProps('password')} />
          <PasswordInput label="Confirm password" autoComplete="new-password" size="md" {...form.getInputProps('confirm')} />
          <Button type="submit" size="md" loading={busy} fullWidth>Save password</Button>
        </Stack>
      </form>
    </AuthCard>
  );
}
