"use client";

import { LogOut } from "lucide-react";
import { useTranslations } from "next-intl";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useRouter } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { getInitials } from "@/lib/utils";

export function AccountSwitcher() {
  const { user, logout } = useAuth();
  const t = useTranslations("AccountSwitcher");
  const router = useRouter();

  if (!user) {
    return null;
  }

  const fullName = `${user.first_name} ${user.last_name}`;

  async function handleLogout() {
    await logout();
    // Un seul point de connexion pour toute la plateforme : la page signin
    // de landing — cf. AuthGuard. Navigation interne (même origine).
    router.push("/signin");
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Avatar className="size-8 rounded-lg">
          <AvatarFallback>{getInitials(fullName)}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="min-w-56 space-y-1 rounded-lg" side="bottom" align="end" sideOffset={4}>
        <DropdownMenuLabel className="p-0">
          <div className="flex w-full items-center gap-2 px-1 py-1.5">
            <Avatar className="size-9 rounded-lg">
              <AvatarFallback>{getInitials(fullName)}</AvatarFallback>
            </Avatar>
            <div className="grid min-w-0 flex-1 text-left text-sm leading-tight">
              <span className="truncate font-semibold">{fullName}</span>
              <span className="truncate text-muted-foreground text-xs">{user.email}</span>
              <span className="truncate text-xs capitalize">{user.role.toLowerCase()}</span>
            </div>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={handleLogout}>
          <LogOut />
          {t("logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
