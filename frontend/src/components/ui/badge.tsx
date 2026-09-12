import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground shadow hover:bg-primary/80",
        secondary: "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive: "border-transparent bg-destructive text-destructive-foreground shadow hover:bg-destructive/80",
        outline: "text-foreground",
        // 상태 칩. 판정 3색(검증=초록, 대기=호박, 실패=빨강)은 옅은 면 위에
        // 같은 계열 글자로 올린다 — 값이 아니라 상태를 말하는 자리라
        // 채운 배지보다 조용해야 한다.
        success: "border-transparent bg-ok-soft text-ok-text",
        warning: "border-transparent bg-warn-soft text-warn-text",
        error: "border-transparent bg-destructive-soft text-destructive",
        // 진행 중 — 판정색을 쓸 수 없는 자리.
        running: "border-transparent bg-highlight-soft text-highlight",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
export { Badge, badgeVariants };
