import type { ReactNode, ComponentType } from 'react'

export interface NavItem {
  path: string
  label: string
  icon: ComponentType<{ className?: string }>
  group?: string
}

export interface FilterBarProps {
  disabled?: boolean
  hideProjectFilter?: boolean
}

export interface DashboardLayoutProps {
  children: ReactNode
  topBar?: ReactNode
  sidebar?: ReactNode
  sidebarProps?: Partial<DashboardSidebarProps>
  filterBarProps?: FilterBarProps
}

export interface DashboardSidebarProps {
  items: NavItem[]
  footer?: ReactNode
  onNavClick?: () => void
  showCloseButton?: boolean
  hideLogo?: boolean
}

export interface DashboardNavProps {
  item: NavItem
  onClick?: () => void
}

export interface DashboardMobileDrawerProps {
  isOpen: boolean
  onClose: () => void
  topContent?: ReactNode
  children: ReactNode
}
