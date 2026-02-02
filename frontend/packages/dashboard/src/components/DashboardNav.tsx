import { Link, useLocation } from 'react-router-dom'
import type { DashboardNavProps } from './types'

export function DashboardNav({ item, onClick }: DashboardNavProps) {
  const location = useLocation()
  const isActive = location.pathname === item.path
  const Icon = item.icon

  return (
    <Link
      to={item.path}
      onClick={onClick}
      className={`flex items-center gap-3 px-3 py-2 text-sm transition-colors rounded-md ${
        isActive
          ? 'bg-primary/10 text-primary font-medium border-l-2 border-primary'
          : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
      }`}
    >
      <Icon className="h-4 w-4" />
      {item.label}
    </Link>
  )
}
