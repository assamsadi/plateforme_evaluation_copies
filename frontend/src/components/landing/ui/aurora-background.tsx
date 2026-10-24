"use client"

import type React from "react"
import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

interface AuroraBackgroundProps extends React.HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  showRadialGradient?: boolean
  /** Animation duration in seconds. Default is 60s for subtle movement. Use lower values (10-20s) for more visible animation. */
  animationSpeed?: number
}

export const AuroraBackground = ({
  className,
  children,
  showRadialGradient = true,
  animationSpeed = 60,
  ...props
}: AuroraBackgroundProps) => {
  return (
    <main>
      <div
        className={cn(
          "transition-bg relative flex min-h-screen flex-col items-center bg-zinc-50 text-slate-950",
          className,
        )}
        {...(props as any)}
      >
        <div
          className="absolute inset-0 overflow-hidden"
          style={
            {
              "--aurora":
                "repeating-linear-gradient(100deg,#ffffff_10%,#10b981_15%,#ffffff_20%,#059669_25%,#ffffff_30%)",
              "--white-gradient":
                "repeating-linear-gradient(100deg,#fff_0%,#fff_7%,transparent_10%,transparent_12%,#fff_16%)",

              "--color-1": "#ffffff",
              "--color-2": "#10b981",
              "--color-3": "#ffffff",
              "--color-4": "#059669",
              "--color-5": "#ffffff",
              "--white": "#fff",
              "--transparent": "transparent",
              "--animation-speed": `${animationSpeed}s`,
            } as React.CSSProperties
          }
        >
          <div
            className={cn(
              `pointer-events-none absolute -inset-[10px] [background-image:var(--white-gradient),var(--aurora)] [background-size:300%,_200%] [background-position:50%_50%,50%_50%] opacity-50 blur-[10px] invert filter will-change-transform [--aurora:repeating-linear-gradient(100deg,var(--color-1)_10%,var(--color-2)_15%,var(--color-3)_20%,var(--color-4)_25%,var(--color-5)_30%)] [--white-gradient:repeating-linear-gradient(100deg,var(--white)_0%,var(--white)_7%,var(--transparent)_10%,var(--transparent)_12%,var(--white)_16%)] after:absolute after:inset-0 after:[background-image:var(--white-gradient),var(--aurora)] after:[background-size:200%,_100%] after:[background-attachment:fixed] after:mix-blend-difference after:content-[""]`,
              "after:[animation:aurora_var(--animation-speed)_linear_infinite]",
              showRadialGradient &&
                "[mask-image:radial-gradient(ellipse_at_100%_0%,black_10%,var(--transparent)_70%)]",
            )}
          />
        </div>
        {children}
      </div>
    </main>
  )
}

export default AuroraBackground
