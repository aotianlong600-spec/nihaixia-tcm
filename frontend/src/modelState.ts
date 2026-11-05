export const isValidatedModelResult=(job:{status:string;validated?:boolean;stale?:boolean}|null):boolean => job?.status==='completed'&&job.validated===true&&job.stale!==true
