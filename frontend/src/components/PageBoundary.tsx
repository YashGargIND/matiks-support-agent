import {Component,type ReactNode} from 'react'
import {Button} from './ui/button'
import {Alert,AlertTitle,AlertDescription} from './ui/alert'
export default class PageBoundary extends Component<{children:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return {failed:true}}render(){return this.state.failed?<main className="standard-page"><Alert><AlertTitle>This view could not be displayed</AlertTitle><AlertDescription>The rest of the navigation and safe-mode information still work. Refresh this view to reload the current data.<Button variant="outline" onClick={()=>window.location.reload()}>Refresh view</Button></AlertDescription></Alert></main>:this.props.children}}
