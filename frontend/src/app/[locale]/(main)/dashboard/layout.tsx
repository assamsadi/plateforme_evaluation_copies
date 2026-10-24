import type { ReactNode } from "react";

import { cookies } from "next/headers";

import { AppSidebar } from "@/app/[locale]/(main)/dashboard/_components/sidebar/app-sidebar";
import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { getPreference } from "@/server/server-actions";

import { AccountSwitcher } from "./_components/header/account-switcher";
import { LayoutControls } from "./_components/header/layout-controls";
import { SearchDialog } from "./_components/header/search-dialog";
import { ThemeSwitcher } from "./_components/header/theme-switcher";

export default async function Layout({ children }: Readonly<{ children: ReactNode }>) {
  const cookieStore = await cookies();
  const defaultOpen = cookieStore.get("sidebar_state")?.value !== "false";
  const [variant, collapsible] = await Promise.all([
    getPreference("sidebar_variant"),
    getPreference("sidebar_collapsible"),
  ]);

  return (
    <AuthGuard>
      <SidebarProvider
        defaultOpen={defaultOpen}
        style={
          {
            "--sidebar-width": "calc(var(--spacing) * 68)",
          } as React.CSSProperties
        }
      >
        <AppSidebar variant={variant} collapsible={collapsible} />
        <SidebarInset
          className={cn(
            "[html[data-content-layout=centered]_&>*]:mx-auto",
            "[html[data-content-layout=centered]_&>*]:w-full",
            "[html[data-content-layout=centered]_&>*]:max-w-screen-2xl",
            "peer-data-[variant=inset]:border",
            "[--dashboard-header-height:--spacing(16)]",
            "min-w-0 overflow-x-clip bg-background",
          )}
        >
          <header
            className={cn(
              "flex h-16 shrink-0 items-center gap-2 border-b border-sidebar-border bg-sidebar/95 transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-16",
              "[html[data-navbar-style=sticky]_&]:sticky [html[data-navbar-style=sticky]_&]:top-0 [html[data-navbar-style=sticky]_&]:z-50 [html[data-navbar-style=sticky]_&]:overflow-hidden [html[data-navbar-style=sticky]_&]:rounded-t-[inherit] [html[data-navbar-style=sticky]_&]:backdrop-blur-md",
            )}
          >
            <div className="flex w-full items-center justify-between px-3 lg:px-5">
              <div className="flex items-center gap-1 lg:gap-2">
                <SidebarTrigger className="-ml-1 size-7 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground" />
                <SearchDialog />
              </div>
              <div className="flex items-center gap-1.5">
                <ThemeSwitcher />
                <LayoutControls />
                <AccountSwitcher />
              </div>
            </div>
          </header>
          <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden p-4 has-data-[content-padding=false]:p-0 md:p-6 md:has-data-[content-padding=false]:p-0">
            {children}
          </div>
        </SidebarInset>
      </SidebarProvider>
    </AuthGuard>
  );
}
