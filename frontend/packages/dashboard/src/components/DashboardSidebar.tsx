import { Link } from 'react-router-dom'
import { X } from 'lucide-react'
import { DashboardNav } from './DashboardNav'
import type { DashboardSidebarProps } from './types'

export function DashboardSidebar({
  items,
  footer,
  onNavClick,
  showCloseButton,
  hideLogo,
}: DashboardSidebarProps) {
  return (
    <div className="flex flex-col h-full">
      {/* Logo - hidden when topBar provides branding */}
      {!hideLogo && (
        <div className={`flex h-14 items-center px-4 border-b ${showCloseButton ? 'justify-between' : 'gap-2'}`}>
          <Link to="/" className="flex items-center gap-2" onClick={onNavClick}>
            <span className="text-xl leading-none text-primary" aria-hidden="true">&#x2B55;</span>
            <span className="font-semibold tracking-tight">BeadHub</span>
          </Link>
          {showCloseButton && (
            <button
              onClick={onNavClick}
              className="p-2 hover:bg-secondary/50 rounded-md"
              aria-label="Close navigation"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      )}

      {/* Navigation */}
      <nav className={`flex-1 px-3 ${hideLogo ? 'py-3' : 'py-4'}`}>
        {items.map((item, index) => {
          const prevItem = items[index - 1]
          const isNewGroup = index > 0 && item.group !== prevItem?.group
          return (
            <div key={item.path}>
              {isNewGroup && (
                <div className="mt-4 mb-1 pt-3 mx-1 border-t border-border/60">
                  {item.group && (
                    <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      {item.group}
                    </span>
                  )}
                </div>
              )}
              <DashboardNav
                item={item}
                onClick={onNavClick}
              />
            </div>
          )
        })}
      </nav>

      {/* Footer (optional - for theme toggle, account info, etc.) */}
      {footer && (
        <div className="p-4 border-t">
          {footer}
        </div>
      )}
    </div>
  )
}
