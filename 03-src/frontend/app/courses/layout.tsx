import './prototype.css';
import './course-extra.css';
import { CourseSprite } from '@/components/course/CourseUI';

export default function CoursesLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="ifc ifc-shell">
      <CourseSprite />
      {children}
    </div>
  );
}
