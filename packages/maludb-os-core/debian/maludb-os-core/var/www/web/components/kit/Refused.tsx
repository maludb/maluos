/** A refusal shown inside the shell — PHP's message verbatim, because it names what is in the way. */
export default function Refused({ title, message }: { title: string; message: string }) {
  return (
    <div className="main-content">
      <div className="row">
        <div className="col-12">
          <div className="alert alert-danger m-4" role="alert" id="screen-refused">
            <h6 className="fw-bold mb-1">{title}</h6>
            <span>{message}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
