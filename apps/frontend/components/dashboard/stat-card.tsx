import { Card, CardContent } from "@/components/ui/card";

export function StatCard({ label, value, hint, icon }: { label: string; value: React.ReactNode; hint?: string; icon?: React.ReactNode }) {
  return (
    <Card className="overflow-hidden transition hover:-translate-y-0.5 hover:shadow-md">
      <CardContent className="pt-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-black uppercase tracking-[.14em] text-muted-foreground">{label}</p>
            <div className="mt-2 text-3xl font-black tracking-tight text-[var(--brand-navy)] dark:text-foreground">{value}</div>
            {hint && <p className="mt-2 text-xs leading-5 text-muted-foreground">{hint}</p>}
          </div>
          {icon && <div className="grid h-11 w-11 place-items-center rounded-2xl bg-primary/10 text-primary">{icon}</div>}
        </div>
      </CardContent>
    </Card>
  );
}
