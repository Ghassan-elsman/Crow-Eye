## what is Crow Eye 

Crow Eye it windows forensics tool that designed to parse windows artifact 
1. Automatic and Custom jump list 
2. Lnk files 
3. prefetch files
4. Registries 
5. Logs
crow eye parse these Artifacts and represnt them via GUI to be more easy to analyze 


How to use Crow eye
*  Automatic ,Custom jump list and LNK files  
    *  to parse these artifacts you need to copy them and past the files in this `CrowEye/Artifacts Collectors/Target Artifacts`
*  Registries 
	* to parse Registries we need to copy them  into  `CrowEye/Artifacts Collectors/Target Artifacts`   note you can't copy them while your machine running 
	* the register parser will parse computer general info  like(Network inter faces , netwrks compyter was conected to it ,auto run, files and folder activty and much more)
 * prefetch 
	 * the tool will parse it directly parse the prefetch file from 'C:\Windows\Prefetch'
* logs 
	* it will be parsed using win32evtlog and saved into data base
