export const isValidatedModelResult=(job:{status:string;validated?:boolean}|null):boolean => job?.status==='completed'&&job.validated===true
