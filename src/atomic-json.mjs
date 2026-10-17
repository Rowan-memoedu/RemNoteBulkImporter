import {writeFile,rename} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';

/** Windows readers may briefly omit delete-sharing. Keep the old checkpoint
 * intact and retry only the atomic rename; never truncate the destination.
 */
export async function atomicJSON(file,value,{write=writeFile,replace=rename,wait=ms=>new Promise(r=>setTimeout(r,ms))}={}){
  const temp=`${file}.${randomUUID()}.tmp`;
  await write(temp,JSON.stringify(value));
  for(let attempt=0;;attempt++){
    try{await replace(temp,file);return;}
    catch(error){
      if(!['EPERM','EBUSY','EACCES'].includes(error.code)||attempt>=7)throw error;
      await wait(Math.min(25*2**attempt,400));
    }
  }
}
