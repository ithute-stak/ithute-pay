"use client";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTable } from "@/components/dashboard/data-table";
import { useAdminAuditQuery } from "@/store/gateway-api";
export default function Page(){const {data=[],isLoading}=useAdminAuditQuery();return <><PageHeader title="Audit trail" description="Immutable operational evidence for administrative and financial actions."/><DataTable rows={data} empty={isLoading?"Loading audit trail…":"No audit entries yet."} columns={[{key:"action",label:"Action",render:(r:any)=><p className="font-bold text-[#082b4d]">{r.action}</p>},{key:"actor",label:"Actor",render:(r:any)=><span>{r.actor_type} · {r.actor_id||"system"}</span>},{key:"resource",label:"Resource",render:(r:any)=><span>{r.resource_type} · {r.resource_id||"—"}</span>},{key:"created",label:"Time",render:(r:any)=>new Date(r.created_at).toLocaleString()}]}/></>}
