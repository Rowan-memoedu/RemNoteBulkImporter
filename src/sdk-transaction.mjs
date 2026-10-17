/** Some SDK hosts do not reply when an async callback rejects. Capture the
 * callback error, let the host acknowledge, then rethrow it outside that RPC.
 * Partial owned writes remain recoverable; never assume SDK rollback.
 */
export async function sdkTransaction(execute,callback) {
  let failure;
  const result=await execute(async()=>{
    try{return await callback();}catch(error){failure=error;return null;}
  });
  if(failure)throw failure;
  return result;
}
