import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Tailwind class 重複解消 + 条件 join (shadcn/ui 互換)。 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
