import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function money(value: string | number, currency = "LSL") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(value));
}
