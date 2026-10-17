/** Bounded read-only work. Drain in-flight reads on failure before returning;
 * never continue a failed audit in the background or retry mutations here. */
export async function boundedRead(rows,read,concurrency=4){
  if(!Number.isInteger(concurrency)||concurrency<1||concurrency>8)throw new Error('Read concurrency must be 1..8');
  let next=0,failure;
  await Promise.all(Array.from({length:Math.min(rows.length,concurrency)},async()=>{
    while(!failure&&next<rows.length){
      const index=next++;
      try{await read(rows[index],index);}catch(error){failure??=error;}
    }
  }));
  if(failure)throw failure;
}
