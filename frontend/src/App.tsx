import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Layout } from '@/components/Layout'
import { AgentsPage } from '@/pages/AgentsPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { IncidentsPage } from '@/pages/IncidentsPage'
import { MultilingualPage } from '@/pages/MultilingualPage'
import { NewTicketPage } from '@/pages/NewTicketPage'
import { RetentionPage } from '@/pages/RetentionPage'
import { WeeklyReportPage } from '@/pages/WeeklyReportPage'
import { SetupPage } from '@/pages/SetupPage'
import { TicketDetailPage } from '@/pages/TicketDetailPage'
import { TicketsPage } from '@/pages/TicketsPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="tickets" element={<TicketsPage />} />
            <Route path="tickets/new" element={<NewTicketPage />} />
            <Route path="tickets/:id" element={<TicketDetailPage />} />
            <Route path="incidents" element={<IncidentsPage />} />
            <Route path="retention" element={<RetentionPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="reports" element={<WeeklyReportPage />} />
            <Route path="multilingual" element={<MultilingualPage />} />
            <Route path="setup" element={<SetupPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </QueryClientProvider>
  )
}
